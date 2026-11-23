"""Additional title-matched net photos; avoids unrelated tag/description matches."""
from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib
import json
from pathlib import Path
import re
import time
import requests
from collect_openverse import ROOT,download

QUERIES=['fishing nets','fishing net','ghost net','discarded net','fish nets','fishingnets','fishnet','seine net','gill net','gillnet','trawl net','cast net','nets drying','redes de pesca','filets de pêche','Fischernetze','fiskegarn','reti da pesca']
MATCH=re.compile(r'\bnet\b|\bnets\b|fishnet|gillnet|castnet|trawl|redes|pesca|filet|fischernetz|fiskegarn',re.I)
REJECT=re.compile(r'stocking|tights|patent|artwork|painting|flower|koki|delonix|bougain|hibiscus|bra |lingerie',re.I)


def main():
    path=ROOT/'data/candidates.json'
    rows=json.loads(path.read_text(encoding='utf-8'))
    seen={r['source_page'] for r in rows}
    hashes={r['sha256'] for r in rows}
    total=sum(r['group']=='net' for r in rows)
    cache=ROOT/'data/search_cache'
    for query in QUERIES:
        for page in range(1,13):
            cached=cache/(hashlib.sha256(f'title/{query}/{page}'.encode()).hexdigest()+'.json')
            print('SEARCH_TITLE',query,page,'net total',total,flush=True)
            if cached.exists():
                data=json.loads(cached.read_text())
            else:
                r=requests.get('https://api.openverse.org/v1/images/',params={'title':query,'source':'flickr','license':'cc0,pdm,by,by-sa','page_size':20,'page':page},timeout=35)
                if r.status_code==429:
                    print('RATE_LIMIT',r.headers.get('Retry-After'),flush=True)
                    return
                if r.status_code==400:
                    break
                r.raise_for_status()
                data=r.json()
                cached.write_text(json.dumps(data),encoding='utf-8')
                time.sleep(.5)
            items=[i for i in data.get('results',[]) if i['foreign_landing_url'] not in seen and MATCH.search(i.get('title','')) and not REJECT.search(i.get('title',''))]
            with ThreadPoolExecutor(max_workers=4) as pool:
                for future in as_completed([pool.submit(download,item,'net') for item in items]):
                    row=future.result()
                    if row and row['sha256'] not in hashes:
                        rows.append(row)
                        seen.add(row['source_page'])
                        hashes.add(row['sha256'])
                        total+=1
            path.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
            print('NET_TOTAL',total,flush=True)
            if total>=1400:
                return
            if page>=data.get('page_count',1):
                break


if __name__=='__main__':
    main()
