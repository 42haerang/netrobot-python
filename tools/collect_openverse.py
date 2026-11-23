"""Public Openverse search + openly licensed Flickr photos, with resumable metadata."""
from concurrent.futures import ThreadPoolExecutor,as_completed
from io import BytesIO
import hashlib
import json
from pathlib import Path
import time

from PIL import Image,ImageOps
import requests

ROOT=Path(__file__).resolve().parents[1]
QUERIES={
    'net':['fishing nets','fishing net','fishnet fishing','fishing seine','fishing net detail','fishing gillnet','fishing cast net','abandoned fishing net','fishing trawl net','fishing nets drying','fish net mesh'],
    'lookalike':['chain link fence detail','wire mesh fence','woven basket texture','metal grating','wicker basket detail','chainlink fence','wire fence close up','woven fabric texture'],
    'other':['sand texture beach','pebbles beach','driftwood beach','empty beach','plastic bottle beach','rocks beach'],
}
TARGETS={'net':700,'lookalike':360,'other':240}


def download(item,group):
    ident=item['id'].replace('-','')[:20]
    target=ROOT/'data/raw'/group/(ident+'.jpg')
    target.parent.mkdir(parents=True,exist_ok=True)
    try:
        if not target.exists():
            response=requests.get(item['url'],timeout=25)
            if response.status_code==429:
                return None
            response.raise_for_status()
            image=ImageOps.exif_transpose(Image.open(BytesIO(response.content))).convert('RGB')
            if min(image.size)<180:
                return None
            image.thumbnail((768,768))
            image.save(target,quality=91)
        image=Image.open(target).convert('RGB')
        pixels=list(image.resize((9,8)).convert('L').getdata())
        dhash=0
        for y in range(8):
            for x in range(8):
                dhash=(dhash<<1)|int(pixels[y*9+x]>pixels[y*9+x+1])
        return {'id':ident,'group':group,'commons_title':item.get('title',''),'source_page':item['foreign_landing_url'],
                'download_url':item['url'],'original_url':item['url'],'author':item.get('creator',''),
                'license':item['license'],'license_url':item.get('license_url',''),'file':target.relative_to(ROOT).as_posix(),
                'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'dhash':f'{dhash:016x}',
                'image_width':image.width,'image_height':image.height,'reviewed':False,'boxes':None,'provider':'Openverse/Flickr'}
    except (requests.RequestException,ValueError,OSError):
        return None


def main():
    manifest=ROOT/'data/candidates.json'
    rows=json.loads(manifest.read_text(encoding='utf-8')) if manifest.exists() else []
    seen={r['source_page'] for r in rows}
    seen_urls={r['download_url'] for r in rows}
    hashes={r['sha256'] for r in rows}
    cache=ROOT/'data/search_cache'
    cache.mkdir(exist_ok=True)
    for group,queries in QUERIES.items():
        total=sum(r['group']==group for r in rows)
        for query in queries:
            if total>=TARGETS[group]:
                break
            for page in range(1,6):
                print('SEARCH',group,query,page,'have',total,flush=True)
                cached=cache/(hashlib.sha256(f'{query}/{page}'.encode()).hexdigest()+'.json')
                if cached.exists():
                    result=json.loads(cached.read_text(encoding='utf-8'))
                else:
                    response=requests.get('https://api.openverse.org/v1/images/',params={'q':query,'page_size':20,'page':page,'source':'flickr','license':'cc0,pdm,by,by-sa'},timeout=35)
                    if response.status_code==429:
                        seconds=int(response.headers.get('Retry-After','60'))
                        print('RATE_LIMIT',seconds,flush=True)
                        time.sleep(min(seconds,3600))
                        break
                    response.raise_for_status()
                    result=response.json()
                    cached.write_text(json.dumps(result),encoding='utf-8')
                    time.sleep(.6)
                items=[i for i in result.get('results',[]) if i['foreign_landing_url'] not in seen and i['url'] not in seen_urls]
                with ThreadPoolExecutor(max_workers=4) as pool:
                    for future in as_completed([pool.submit(download,item,group) for item in items]):
                        row=future.result()
                        if row is None or row['sha256'] in hashes:
                            continue
                        rows.append(row)
                        seen.add(row['source_page'])
                        seen_urls.add(row['download_url'])
                        hashes.add(row['sha256'])
                        total+=1
                manifest.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
                print('SAVED',group,total,flush=True)
                if total>=TARGETS[group] or page>=result.get('page_count',1):
                    break
        print('GROUP_DONE',group,total,flush=True)


if __name__=='__main__':
    main()
