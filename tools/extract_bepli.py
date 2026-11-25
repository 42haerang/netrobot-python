"""Safely extract publisher split images and COCO labels from BePLi v2.

The duplicate original_images directory is skipped. Source files are retained;
this script never uses the deprecated web-search collection.
"""
import argparse
import json
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import time


def extract(archive, output):
    archive, output = Path(archive).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    marker = output / 'EXTRACTED.json'
    if marker.exists():
        print(marker.read_text(encoding='utf-8'), flush=True)
        return
    copied, skipped, last = 0, 0, time.monotonic()
    with tarfile.open(archive, 'r|gz') as source:
        for member in source:
            path = PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts or any(':' in p for p in path.parts):
                raise ValueError('Unsafe archive member: ' + member.name)
            if member.isdir():
                continue
            if not member.isfile():
                raise ValueError('Unexpected link or special archive member: ' + member.name)
            if 'original_images' in path.parts:
                skipped += 1
                continue
            target = (output / Path(*path.parts)).resolve()
            if not target.is_relative_to(output):
                raise ValueError('Archive path outside destination')
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.extractfile(member) as incoming, target.open('wb') as outgoing:
                shutil.copyfileobj(incoming, outgoing, length=1024 * 1024)
            if target.stat().st_size != member.size:
                raise ValueError('Incomplete file: ' + member.name)
            copied += 1
            if time.monotonic() - last > 10:
                print(f'EXTRACTING copied={copied} skipped_originals={skipped}', flush=True)
                last = time.monotonic()
    report = {'archive': str(archive), 'copied': copied, 'skipped_originals': skipped}
    marker.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('EXTRACTION_COMPLETE', report, flush=True)
    for filename in output.rglob('*.json'):
        if filename == marker:
            continue
        data = json.loads(filename.read_text(encoding='utf-8'))
        if 'categories' in data:
            counts = {c['id']: 0 for c in data['categories']}
            for ann in data.get('annotations', []):
                counts[ann['category_id']] += 1
            print('COCO', filename, 'images', len(data.get('images', [])),
                  'categories', [(c['id'], c['name'], counts[c['id']]) for c in data['categories']], flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    extract(args.archive, args.output)
