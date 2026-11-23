"""Render a numbered sheet for dataset QA; source photos remain unchanged."""
import argparse
import json
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont

ROOT=Path(__file__).resolve().parents[1]


def sheet(group,start,count=64):
    rows=[r for r in json.loads((ROOT/'data/candidates.json').read_text(encoding='utf-8')) if r['group']==group]
    columns=8
    cellw,cellh=200,166
    page=Image.new('RGB',(columns*cellw,((count+columns-1)//columns)*cellh),'#17202d')
    draw=ImageDraw.Draw(page)
    try:
        font=ImageFont.truetype('Arial.ttf',16)
    except OSError:
        font=ImageFont.load_default(size=16)
    for local,row in enumerate(rows[start:start+count]):
        x,y=(local%columns)*cellw,(local//columns)*cellh
        image=Image.open(ROOT/row['file']).convert('RGB')
        image.thumbnail((cellw-6,cellh-26))
        page.paste(image,(x+(cellw-image.width)//2,y))
        draw.text((x+5,y+cellh-23),f'{group} {start+local}',font=font,fill='white')
    destination=ROOT/'data/qa'/f'{group}_{start:04d}.jpg'
    destination.parent.mkdir(exist_ok=True)
    page.save(destination,quality=90)
    return destination


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('group')
    parser.add_argument('start',type=int)
    parser.add_argument('--count',type=int,default=64)
    args=parser.parse_args()
    print(sheet(args.group,args.start,args.count))
