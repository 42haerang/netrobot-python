"""Exactly 500/300/200 unique photographs, 800 development + 200 held-out test."""
import csv
import json
from pathlib import Path
import random
import shutil

ROOT=Path(__file__).resolve().parents[1]
TARGETS={'net':500,'lookalike':300,'other':200}


def prepare():
    rows=json.loads((ROOT/'data/candidates.json').read_text(encoding='utf-8'))
    decisions=json.loads((ROOT/'data/review.json').read_text(encoding='utf-8'))
    random.Random(2027).shuffle(rows)
    selected=[]
    hashes=set()
    perceptual=[]
    for group,target in TARGETS.items():
        accepted=[]
        for row in rows:
            if row['group']!=group or row['id'] not in decisions:
                continue
            decision=decisions[row['id']]
            if not decision.get('accepted') or not decision.get('reviewed'):
                continue
            if group=='net' and not decision.get('boxes'):
                continue
            if row['sha256'] in hashes:
                continue
            phash=int(row['dhash'],16)
            if any((phash ^ old).bit_count()<=3 for old in perceptual):
                continue
            hashes.add(row['sha256'])
            perceptual.append(phash)
            accepted.append({**row,**decision})
            if len(accepted)==target:
                break
        if len(accepted)!=target:
            raise ValueError(f'{group}: verified unique images {len(accepted)}/{target}; collect/review more photos')
        # Every source file appears in one split only; no augmentation is counted as a photo.
        train_count=int(target*.8)
        for index,row in enumerate(accepted):
            row['split']='train' if index<train_count else 'test'
        selected.extend(accepted)
    dataset=ROOT/'data/dataset'
    if dataset.exists():
        raise FileExistsError('data/dataset already exists; retain the existing split rather than overwriting it')
    for split in ('train','test'):
        (dataset/'images'/split).mkdir(parents=True)
        (dataset/'labels'/split).mkdir(parents=True)
    for row in selected:
        split=row['split']
        shutil.copy2(ROOT/row['file'],dataset/'images'/split/(row['id']+'.jpg'))
        lines=[]
        for x1,y1,x2,y2 in row.get('boxes',[]):
            if not (0<=x1<x2<=1 and 0<=y1<y2<=1):
                raise ValueError('Invalid normalized box: '+row['id'])
            lines.append(f'0 {(x1+x2)/2:.7f} {(y1+y2)/2:.7f} {x2-x1:.7f} {y2-y1:.7f}')
        (dataset/'labels'/split/(row['id']+'.txt')).write_text('\n'.join(lines),encoding='utf-8')
    (ROOT/'data/manifest.json').write_text(json.dumps(selected,ensure_ascii=False,indent=2),encoding='utf-8')
    fields=['id','group','split','source_page','author','license','license_url','sha256']
    with (ROOT/'data/SOURCES.csv').open('w',encoding='utf-8-sig',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=fields,extrasaction='ignore')
        writer.writeheader()
        writer.writerows(selected)
    report={'total':len(selected),'train':800,'test':200,'groups':TARGETS,'duplicates_removed':True,'test_is_held_out':True}
    (ROOT/'data/dataset_report.json').write_text(json.dumps(report,indent=2))
    print('DATASET_READY',report,flush=True)


if __name__=='__main__':
    prepare()
