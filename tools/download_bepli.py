"""Download the official, manually annotated BePLi v2 archive; never scrape search images.

Source: https://doi.org/10.17882/96963 (CC BY-NC-SA 4.0).
The archive is about 9.5 GB. Interrupted downloads can resume using HTTP ranges.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time

import requests

URL='https://www.seanoe.org/data/00857/96963/data/106157.tar.gz'
ROOT=Path(__file__).resolve().parents[1]


def download(output):
    output=Path(output)
    output.mkdir(parents=True,exist_ok=True)
    archive=output/'106157.tar.gz'
    partial=output/'106157.tar.gz.part'
    session=requests.Session()
    # Resolve the official download link recorded in the landing page.
    from bs4 import BeautifulSoup
    response=session.get('https://www.seanoe.org/data/00857/96963/',timeout=40)
    response.raise_for_status()
    soup=BeautifulSoup(response.text,'html.parser')
    from urllib.parse import urljoin,urlparse
    links=[urljoin(response.url,a['href']) for a in soup.find_all('a',href=True) if a['href'].split('?')[0].endswith('/106157.tar.gz')]
    if not links:
        raise RuntimeError('Official archive link is no longer present; check the dataset landing page.')
    url=links[0]
    if urlparse(url).hostname not in ('www.seanoe.org','seanoe.org','www.ifremer.fr','data-dataref.ifremer.fr'):
        raise RuntimeError('Unexpected archive host; inspect the official download page.')
    print('OFFICIAL_ARCHIVE',url,flush=True)
    with session.head(url,allow_redirects=True,timeout=40) as head:
        head.raise_for_status()
        size=int(head.headers['Content-Length'])
        metadata={'dataset':'BePLi v2','doi':'10.17882/96963','source_page':'https://www.seanoe.org/data/00858/96963/',
                  'download_url':url,'license':'CC BY-NC-SA 4.0','license_url':'https://creativecommons.org/licenses/by-nc-sa/4.0/',
                  'expected_bytes':size,'etag':head.headers.get('ETag'),'last_modified':head.headers.get('Last-Modified'),
                  'labels':'Publisher-provided manual COCO instance annotations','download_complete':False}
    if archive.exists():
        if archive.stat().st_size!=size:
            raise RuntimeError('Existing archive has an unexpected size; preserve it and inspect before retrying.')
        print('ARCHIVE_ALREADY_PRESENT',size,flush=True)
    else:
        for attempt in range(4):
            offset=partial.stat().st_size if partial.exists() else 0
            headers={'Range':f'bytes={offset}-','Accept-Encoding':'identity'} if offset else {'Accept-Encoding':'identity'}
            if offset and metadata['etag']:
                headers['If-Range']=metadata['etag']
            try:
                with session.get(url,headers=headers,stream=True,timeout=(30,120)) as stream:
                    stream.raise_for_status()
                    if offset and (stream.status_code!=206 or not stream.headers.get('Content-Range','').startswith(f'bytes {offset}-')):
                        raise RuntimeError('Server did not honor resume range; preserve partial file and inspect.')
                    if stream.headers.get('Content-Encoding','identity')!='identity':
                        raise RuntimeError('Unexpected transfer encoding for byte-exact download')
                    start=time.monotonic()
                    last=start
                    with partial.open('ab' if offset else 'wb') as target:
                        for chunk in stream.iter_content(4*1024*1024):
                            if not chunk: continue
                            target.write(chunk)
                            if time.monotonic()-last>10:
                                done=target.tell()
                                elapsed=max(1,time.monotonic()-start)
                                print('DOWNLOAD',round(done/size*100,1),'percent',round(done/1e6),'MB','speed_MB_s',round((done-offset)/1e6/elapsed,1),flush=True)
                                last=time.monotonic()
                if partial.stat().st_size!=size:
                    raise requests.ConnectionError('Incomplete transfer')
                partial.rename(archive)
                break
            except requests.RequestException as exc:
                print('TRANSFER_INTERRUPTED',type(exc).__name__,'attempt',attempt+1,flush=True)
                if attempt==3: raise
                time.sleep(min(2**attempt,8))
    print('HASHING_ARCHIVE',flush=True)
    with archive.open('rb') as source:
        metadata['sha256']=hashlib.file_digest(source,'sha256').hexdigest()
    metadata.update(download_complete=True,actual_bytes=archive.stat().st_size)
    (output/'SOURCE.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    (output/'ATTRIBUTION.txt').write_text('Mitsuko Hidaka, Koshiro Murakami, Shintaro Kawahara, Daisuke Sugiyama, Yujin Nakagawa, Shin\u2019ichiro Kako, Daisuke Matsuoka (2023). BePLi Dataset v2: Beach Plastic Litter Dataset version 2. SEANOE. https://doi.org/10.17882/96963\nCC BY-NC-SA 4.0: https://creativecommons.org/licenses/by-nc-sa/4.0/\nOriginal archive downloaded unchanged; derived subsets must document their modifications.\n',encoding='utf-8')
    print('DOWNLOAD_COMPLETE',archive,'bytes',archive.stat().st_size,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=ROOT/'data/labeled_sources/BePLi_v2/source')
    download(parser.parse_args().output)
