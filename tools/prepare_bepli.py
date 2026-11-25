"""Prepare 1,000 real, publisher-labeled images, retaining BePLi's split boundary.

700 training + 100 validation = 800 development images; 200 held-out tests.
Groups total 500 net / 300 rope-or-string negatives / 200 other negatives.
Net negatives have empty YOLO labels, never a separate 'not net' class.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import random
import shutil

from PIL import Image, ImageDraw, ImageOps

QUOTAS = {'test': {'net': 100, 'lookalike': 60, 'other': 40},
          'val': {'net': 50, 'lookalike': 30, 'other': 20},
          'train': {'net': 350, 'lookalike': 210, 'other': 140}}


def difference_hash(image):
    pixels = list(image.convert('L').resize((9, 8)).getdata())
    return sum(int(pixels[y*9+x] > pixels[y*9+x+1]) << (y*8+x)
               for y in range(8) for x in range(8))


def prepare(source, output, quotas=None, retired_test_manifest=None):
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError('Preserve the existing dataset and split: ' + str(output))
    rng = random.Random(2027)
    quotas = quotas or QUOTAS
    retired_ids = set()
    if retired_test_manifest:
        retired_ids = {r['source_id'] for r in json.loads(Path(retired_test_manifest).read_text(encoding='utf-8')) if r['split']=='test'}
    selected, exact, perceptual, inventory, rejected = [], set(), [], {}, Counter()
    # Test/validation candidates are selected first; conflicting training images
    # are dropped, never moved across the publisher's original split boundary.
    for split, targets in quotas.items():
        data = json.loads((source/'annotation'/f'{split}.json').read_text(encoding='utf-8'))
        cats = {c['id']: c['name'] for c in data['categories']}
        if 'fishing_net' not in cats.values():
            raise ValueError('Publisher fishing_net category is missing')
        annotations = defaultdict(list)
        for a in data['annotations']:
            annotations[a['image_id']].append(a)
        groups = defaultdict(list)
        for image in data['images']:
            if split=='test' and image['id'] in retired_ids:
                continue
            anns = annotations[image['id']]
            nets = [a for a in anns if cats[a['category_id']] == 'fishing_net']
            group = 'net' if nets else 'lookalike' if any(cats[a['category_id']] in ('rope', 'other_string') for a in anns) else 'other'
            path = (source/'images'/split/image['file_name']).resolve()
            if not path.is_relative_to(source/'images'/split) or not path.is_file():
                raise ValueError('Missing or unsafe source image')
            boxes = []
            for a in nets:
                if a.get('iscrowd', 0) or a.get('ignore', 0):
                    raise ValueError('Unresolved ignored/crowd annotation')
                x, y, w, h = a['bbox']
                x1, y1 = max(0, x), max(0, y)
                x2, y2 = min(image['width'], x+w), min(image['height'], y+h)
                if x2 <= x1 or y2 <= y1:
                    raise ValueError('Invalid publisher net box')
                boxes.append([x1, y1, x2, y2])
            groups[group].append({'source_id': image['id'], 'source_file': str(path),
                                  'width': image['width'], 'height': image['height'],
                                  'split': split, 'group': group, 'boxes': boxes})
        inventory[split] = {group: len(rows) for group, rows in groups.items()}
        for group, target in targets.items():
            candidates = groups[group]
            rng.shuffle(candidates)
            accepted = 0
            for row in candidates:
                path = Path(row['source_file'])
                with path.open('rb') as source_image:
                    digest = hashlib.file_digest(source_image, 'sha256').hexdigest()
                if digest in exact:
                    rejected['exact_duplicate'] += 1
                    continue
                with Image.open(path) as image:
                    if image.size != (row['width'], row['height']):
                        raise ValueError('Image dimensions differ from COCO metadata')
                    dhash = difference_hash(image)
                if any((dhash ^ previous).bit_count() <= 3 for previous in perceptual):
                    rejected['near_duplicate_dhash_le_3'] += 1
                    continue
                exact.add(digest)
                perceptual.append(dhash)
                row.update(sha256=digest, dhash=f'{dhash:016x}')
                selected.append(row)
                accepted += 1
                if accepted == target:
                    break
            if accepted != target:
                raise ValueError(f'{split}/{group}: {accepted}/{target} unique images; do not fill with search candidates')
        print('SELECTED', split, sum(targets.values()), flush=True)
    if len({r['source_id'] for r in selected}) != len(selected):
        raise ValueError('Source image ID reused across publisher splits')
    for row in selected:
        split = row['split']
        image_dir, label_dir = output/'images'/split, output/'labels'/split
        image_dir.mkdir(parents=True, exist_ok=True)
        label_dir.mkdir(parents=True, exist_ok=True)
        stem = f"bepli_{row['source_id']:06d}"
        target = image_dir/(stem+'.png')
        shutil.copy2(row['source_file'], target)
        lines = []
        for x1, y1, x2, y2 in row['boxes']:
            w, h = row['width'], row['height']
            lines.append(f'0 {(x1+x2)/2/w:.8f} {(y1+y2)/2/h:.8f} {(x2-x1)/w:.8f} {(y2-y1)/h:.8f}')
        (label_dir/(stem+'.txt')).write_text('\n'.join(lines), encoding='utf-8')
        row['prepared_file'] = target.relative_to(output).as_posix()
    config = 'path: '+json.dumps(output.as_posix())+'\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n  0: net\n'
    (output/'data.yaml').write_text(config, encoding='utf-8')
    report = {'source': 'BePLi v2', 'doi': '10.17882/96963', 'source_url': 'https://doi.org/10.17882/96963',
              'source_license': 'CC BY-NC-SA 4.0', 'labels': 'Publisher manual fishing_net COCO boxes',
              'seed': 2027, 'total': len(selected), 'train': 700, 'val': 100, 'test': 200,
              'development': 800, 'groups': dict(Counter(r['group'] for r in selected)),
              'split_groups': quotas, 'inventory': inventory, 'rejected_duplicates': dict(rejected),
              'retired_test_ids_excluded': sorted(retired_ids),
              'publisher_splits_preserved': True, 'test_is_held_out': True,
              'duplicate_check': 'Original SHA256 and 64-bit dHash Hamming distance <=3; not a guarantee of scene independence',
              'synthetic_images': 0, 'legacy_search_images': 0}
    (output/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    (output/'manifest.json').write_text(json.dumps(selected, ensure_ascii=False, indent=2), encoding='utf-8')
    # Inspect training samples only, so test content cannot influence tuning.
    review = output/'review'
    review.mkdir()
    train_nets = [r for r in selected if r['split']=='train' and r['group']=='net']
    for sheet_number in range(3):
        sheet = Image.new('RGB', (1080, 680), '#111827')
        draw = ImageDraw.Draw(sheet)
        for index, row in enumerate(train_nets[sheet_number*12:(sheet_number+1)*12]):
            x, y = index%3*360, index//3*170
            with Image.open(row['source_file']) as original:
                image = original.convert('RGB')
                overview = ImageOps.contain(image, (178, 142))
                sheet.paste(overview, (x, y+20))
                scale = overview.width/image.width
                for box in row['boxes']:
                    draw.rectangle([x+box[0]*scale, y+20+box[1]*scale, x+box[2]*scale, y+20+box[3]*scale], outline='#22ff88', width=2)
                largest = max(row['boxes'], key=lambda b:(b[2]-b[0])*(b[3]-b[1]))
                crop = ImageOps.contain(image.crop(tuple(largest)), (178, 142))
                sheet.paste(crop, (x+180, y+20))
            draw.text((x+3, y+3), f"TRAIN {row['source_id']:06d} net x{len(row['boxes'])}", fill='white')
        sheet.save(review/f'train_nets_{sheet_number+1}.jpg', quality=90)
    print('DATASET_READY', json.dumps(report), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='Extracted plastic_coco folder')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    prepare(args.source, args.output)
