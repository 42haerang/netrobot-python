"""Resumable bounded parallel HTTP download for the 9.5 GB official BePLi archive.

Uses advertised HTTP byte ranges, validates each range, and never bypasses authentication
or rate limits. A pre-existing sequential partial download is retained as a verified prefix.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib
import json
from pathlib import Path
import threading
import time
import requests


def main(folder,connections):
    folder=Path(folder)
    url='https://www.seanoe.org/data/00858/96963/data/106157.tar.gz'
    archive=folder/'106157.tar.gz'
    partial=folder/'106157.tar.gz.part'
    state_file=folder/'DOWNLOAD_STATE.json'
    head=requests.head(url,allow_redirects=True,timeout=40)
    head.raise_for_status()
    size=int(head.headers['Content-Length'])
    if head.headers.get('Accept-Ranges')!='bytes':
        raise RuntimeError('Server does not advertise byte ranges')
    if archive.exists():
        if archive.stat().st_size!=size:raise RuntimeError('Existing archive size mismatch')
        print('ARCHIVE_ALREADY_PRESENT',flush=True)
        return
    if state_file.exists():
        state=json.loads(state_file.read_text())
        if state['size']!=size or state.get('etag')!=head.headers.get('ETag'):
            raise RuntimeError('Source changed; preserve existing files and inspect manually')
    else:
        prefix=partial.stat().st_size if partial.exists() else 0
        chunks=[]
        # Larger ranges amortize TCP/TLS setup; eight connections is the hard upper limit.
        for start in range(prefix,size,128*1024*1024):
            chunks.append({'start':start,'end':min(start+128*1024*1024,size)-1,'complete':False})
        state={'url':url,'size':size,'etag':head.headers.get('ETag'),'prefix_bytes':prefix,'chunks':chunks}
        state_file.write_text(json.dumps(state,indent=2))
        with partial.open('r+b' if partial.exists() else 'wb') as f:f.truncate(size)
    lock=threading.Lock()
    progress={}
    last=[time.monotonic()]
    begin=time.monotonic()
    initial=state['prefix_bytes']+sum(c['end']-c['start']+1 for c in state['chunks'] if c['complete'])
    def report(force=False):
        now=time.monotonic()
        if not force and now-last[0]<10:return
        done=state['prefix_bytes']+sum(c['end']-c['start']+1 for c in state['chunks'] if c['complete'])+sum(progress.values())
        rate=(done-initial)/max(now-begin,1)
        print('DOWNLOAD',round(done/size*100,2),'percent',round(done/1e6),'MB','speed_MB_s',round(rate/1e6,2),'eta_minutes',round((size-done)/max(rate,1)/60,1),flush=True)
        last[0]=now
    def fetch(index):
        c=state['chunks'][index]
        expected=c['end']-c['start']+1
        headers={'Range':f"bytes={c['start']}-{c['end']}",'Accept-Encoding':'identity'}
        if state['etag']:headers['If-Range']=state['etag']
        for attempt in range(4):
            try:
                with requests.get(url,headers=headers,stream=True,timeout=(30,120)) as response:
                    if response.status_code==429:
                        raise RuntimeError('Server rate limit: stop and respect Retry-After '+response.headers.get('Retry-After','unspecified'))
                    response.raise_for_status()
                    if response.status_code!=206 or response.headers.get('Content-Range')!=f"bytes {c['start']}-{c['end']}/{size}":
                        raise RuntimeError('Unexpected range response; stop to protect file integrity')
                    count=0
                    digest=hashlib.sha256()
                    with partial.open('r+b') as target:
                        target.seek(c['start'])
                        for data in response.iter_content(256*1024):
                            count+=len(data)
                            if count>expected:raise RuntimeError('Range exceeded expected length')
                            target.write(data)
                            digest.update(data)
                            with lock:
                                progress[index]=count
                                report()
                    if count!=expected:raise requests.ConnectionError('Range was truncated')
                    with lock:
                        progress.pop(index,None)
                        c.update(complete=True,sha256=digest.hexdigest())
                        tmp=state_file.with_suffix('.tmp')
                        tmp.write_text(json.dumps(state,indent=2))
                        tmp.replace(state_file)
                        report(True)
                return
            except requests.RequestException as error:
                print('RETRY_RANGE',index,attempt+1,type(error).__name__,flush=True)
                if attempt==3:raise
                time.sleep(min(2**attempt,8))
    print('RESUMING_PREFIX',state['prefix_bytes'],'bytes','CONNECTIONS',connections,flush=True)
    with ThreadPoolExecutor(max_workers=connections) as pool:
        futures=[pool.submit(fetch,i) for i,c in enumerate(state['chunks']) if not c['complete']]
        for future in as_completed(futures):future.result()
    if not all(c['complete'] for c in state['chunks']):raise RuntimeError('Incomplete chunks')
    # Read back every completed chunk to verify that concurrent writes are byte-exact.
    print('VERIFYING_RANGE_HASHES',flush=True)
    with partial.open('rb') as source:
        for c in state['chunks']:
            source.seek(c['start'])
            remaining=c['end']-c['start']+1
            digest=hashlib.sha256()
            while remaining:
                data=source.read(min(4*1024*1024,remaining))
                if not data:raise RuntimeError('Unexpected end of file')
                remaining-=len(data);digest.update(data)
            if digest.hexdigest()!=c['sha256']:raise RuntimeError('Read-back checksum mismatch')
    if partial.stat().st_size!=size:raise RuntimeError('Final size mismatch')
    partial.rename(archive)
    from download_bepli import download
    download(folder)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--connections',type=int,choices=range(1,9),default=4)
    a=p.parse_args()
    main(a.output,a.connections)
