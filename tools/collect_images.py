"""Download attributed Wikimedia Commons photographs; no fabricated or augmented counts."""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import csv
from html import unescape
from io import BytesIO
import hashlib
import json
from pathlib import Path
import re
import time

from PIL import Image,ImageOps
import requests

ROOT=Path(__file__).resolve().parents[1]
API="https://commons.wikimedia.org/w/api.php"
HEADERS={"User-Agent":"NetRobotEducation/1.0 (noncommercial student vision dataset; Wikimedia Commons attribution retained)"}
CATEGORIES={
    "net":["Fishing net textures","Blue fishing nets","Ghost nets","Gillnets","Drying fishing nets","Seine nets","Cast nets","Hand nets","Trawl nets","Net mending","Fishing nets in France","Fishing nets in India","Fishing nets in Thailand","Fishing nets in Portugal","Fishing nets in Sri Lanka","Fishing nets in Vietnam","Fishing nets in Japan","Fishing nets in Italy","Fishing nets in Spain","Fishing nets"],
    "lookalike":["Chain-link fences","Wire mesh","Wire fences","Metal grates","Wicker baskets","Woven fabrics","Rope textures","Metal gratings"],
    "other":["Sand textures","Pebble beaches","Driftwood on beaches","Plastic bottles","Rocks on beaches","Empty beaches","Sandy beaches"],
}


def api(**params):
    for attempt in range(5):
        try:
            r=requests.get(API,params={"action":"query","format":"json",**params},headers=HEADERS,timeout=40)
            if r.status_code in (429,503):
                raise RuntimeError('Wikimedia rate limit/service unavailable; retry later. Retry-After: '+r.headers.get('Retry-After','unspecified'))
            r.raise_for_status()
            data=r.json()
            if "error" in data:
                raise RuntimeError(str(data["error"]))
            return data
        except (requests.RequestException,ValueError):
            if attempt==4:
                raise
            time.sleep(attempt+1)
    raise RuntimeError("Wikimedia rate limit; try later")


def category_files(name,limit=450):
    titles=[]
    continuation={}
    while len(titles)<limit:
        data=api(list="categorymembers",cmtitle="Category:"+name,cmtype="file",cmlimit=min(500,limit-len(titles)),**continuation)
        titles.extend(r["title"] for r in data.get("query",{}).get("categorymembers",[]))
        continuation=data.get("continue")
        if not continuation:
            break
    return titles


def plain(value):
    return unescape(re.sub("<[^>]+>","",value or ""))


def metadata(titles):
    for start in range(0,len(titles),50):
        data=api(prop="imageinfo",titles="|".join(titles[start:start+50]),iiprop="url|size|mime|extmetadata",iiurlwidth=768)
        for page in data.get("query",{}).get("pages",{}).values():
            if not page.get("imageinfo"):
                continue
            info=page["imageinfo"][0]
            title=page["title"]
            if info.get("mime") not in ("image/jpeg","image/png","image/webp"):
                continue
            if min(info["width"],info["height"])<200:
                continue
            if re.search(r"\b(drawing|diagram|painting|map|logo|flag|engraving|illustration|coat of arms)\b",title,re.I):
                continue
            extra=info.get("extmetadata",{})
            license=plain(extra.get("LicenseShortName",{}).get("value",""))
            if not license:
                continue
            yield {"commons_title":title,"source_page":info.get("descriptionurl",""),"original_url":info["url"],
                   "download_url":info.get("thumburl",info["url"]),"author":plain(extra.get("Artist",{}).get("value","")),
                   "license":license,"license_url":plain(extra.get("LicenseUrl",{}).get("value","")),"width":info["width"],"height":info["height"]}


def download(item,group):
    ident=hashlib.sha256(item["commons_title"].encode()).hexdigest()[:20]
    destination=ROOT/"data/raw"/group/(ident+".jpg")
    destination.parent.mkdir(parents=True,exist_ok=True)
    if not destination.exists():
        for attempt in range(3):
            try:
                response=requests.get(item["download_url"],headers=HEADERS,timeout=35)
                if response.status_code==429:
                    raise RuntimeError('Wikimedia rate limit; stop collection and retry later. Retry-After: '+response.headers.get('Retry-After','unspecified'))
                response.raise_for_status()
                image=ImageOps.exif_transpose(Image.open(BytesIO(response.content))).convert("RGB")
                image.thumbnail((768,768))
                if min(image.size)<180:
                    return None
                image.save(destination,quality=91)
                break
            except (requests.RequestException,OSError,ValueError):
                if attempt==2:
                    return None
                time.sleep(attempt+1)
        else:
            return None
    image=Image.open(destination).convert("RGB")
    small=image.resize((9,8)).convert("L")
    pixels=list(small.getdata())
    dhash=0
    for y in range(8):
        for x in range(8):
            dhash=(dhash<<1)|int(pixels[y*9+x]>pixels[y*9+x+1])
    return {**item,"id":ident,"group":group,"file":str(destination.relative_to(ROOT)).replace('\\','/'),
            "sha256":hashlib.sha256(destination.read_bytes()).hexdigest(),"dhash":f"{dhash:016x}",
            "image_width":image.width,"image_height":image.height,"reviewed":False,"boxes":None}


def collect(targets):
    manifest=ROOT/"data/candidates.json"
    rows=json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else []
    seen={row["commons_title"] for row in rows}
    for group,target in targets.items():
        total=sum(row["group"]==group for row in rows)
        for category in CATEGORIES[group]:
            if total>=target:
                break
            print(f"CATEGORY {group}: {category}, have {total}/{target}",flush=True)
            titles=[t for t in category_files(category) if t not in seen]
            items=list(metadata(titles))
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures=[pool.submit(download,item,group) for item in items[:max(0,target-total+30)]]
                for future in as_completed(futures):
                    row=future.result()
                    if row is None or row["commons_title"] in seen:
                        continue
                    seen.add(row["commons_title"])
                    rows.append(row)
                    total+=1
                    if total%20==0:
                        manifest.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding="utf-8")
                        print(f"DOWNLOADED {group} {total}",flush=True)
            manifest.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding="utf-8")
        print("GROUP_DONE",group,total,flush=True)
    return rows


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--net",type=int,default=600)
    parser.add_argument("--lookalike",type=int,default=350)
    parser.add_argument("--other",type=int,default=250)
    args=parser.parse_args()
    collect(vars(args))
