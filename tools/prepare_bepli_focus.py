"""Prepare a fresh test set and object-focused REAL training crops.

Only training images are cropped, using publisher annotations. Validation and
test images stay unchanged. All boxes intersecting a crop are transformed;
empty negatives remain empty. Original source files are preserved separately.
"""
import argparse
from collections import defaultdict
import json
from pathlib import Path

from PIL import Image
from prepare_bepli import prepare

QUOTAS = {'test': {'net': 50, 'lookalike': 60, 'other': 90},
          'val': {'net': 50, 'lookalike': 40, 'other': 10},
          'train': {'net': 400, 'lookalike': 200, 'other': 100}}


def focus(source, retired, output):
    source, output = Path(source), Path(output)
    prepare(source, output, QUOTAS, retired)
    data = json.loads((source/'annotation/train.json').read_text(encoding='utf-8'))
    names = {c['id']: c['name'] for c in data['categories']}
    annotations = defaultdict(list)
    for ann in data['annotations']:
        annotations[ann['image_id']].append(ann)
    rows = json.loads((output/'manifest.json').read_text(encoding='utf-8'))
    for row in rows:
        if row['split'] != 'train':
            continue
        anns = annotations[row['source_id']]
        wanted = [a for a in anns if names[a['category_id']]=='fishing_net'] if row['group']=='net' else [a for a in anns if names[a['category_id']] in ('rope','other_string')] if row['group']=='lookalike' else anns
        largest = max(wanted, key=lambda a:a['bbox'][2]*a['bbox'][3]) if wanted else None
        w, h = row['width'], row['height']
        if largest:
            x,y,bw,bh = largest['bbox']
            side = max(96, bw*1.8, bh*1.8)
            cw, ch = min(w,side), min(h,side)
            left = max(0,min(w-cw,x+bw/2-cw/2))
            top = max(0,min(h-ch,y+bh/2-ch/2))
            right, bottom = left+cw, top+ch
        else:
            left,top,right,bottom=0,0,w,h
        left,top,right,bottom = map(round,(left,top,right,bottom))
        nw, nh = right-left, bottom-top
        boxes = []
        for x1,y1,x2,y2 in row['boxes']:
            box=[max(0,x1-left),max(0,y1-top),min(nw,x2-left),min(nh,y2-top)]
            if box[2]>box[0] and box[3]>box[1]:
                boxes.append(box)
        if row['group']=='net' and not boxes:
            raise ValueError('Object-focused crop lost every net label')
        row.update(source_boxes=row['boxes'],source_width=w,source_height=h,
                   source_crop=[left,top,right,bottom],boxes=boxes,width=nw,height=nh)
        target = output/row['prepared_file']
        with Image.open(row['source_file']) as image:
            image.crop((left,top,right,bottom)).save(target)
        label=output/'labels/train'/(target.stem+'.txt')
        label.write_text('\n'.join(f'0 {(a+c)/2/nw:.8f} {(b+d)/2/nh:.8f} {(c-a)/nw:.8f} {(d-b)/nh:.8f}' for a,b,c,d in boxes),encoding='utf-8')
    (output/'manifest.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    report=json.loads((output/'report.json').read_text(encoding='utf-8'))
    report.update(training_view='Publisher-object-centered real-image crop, 1.8x context, minimum 96px; no generated photos',
                  cropped_training_images=sum(r['split']=='train' and r['source_crop'] != [0,0,r['source_width'],r['source_height']] for r in rows),
                  validation_and_test_views='Unchanged full source images',previous_baseline_test_retired=True)
    (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('FOCUSED_REAL_TRAINING_IMAGES_READY',len(rows),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('retired_test_manifest',type=Path)
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    focus(args.source,args.retired_test_manifest,args.output)
