"""공식 BePLi 사진 내려받기·압축 해제·학습용 선별을 모았습니다.

원본 사진과 발행자의 수작업 라벨만 사용합니다. 검색 사진은 쓰지 않습니다.
"""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path, PurePosixPath
import random
import shutil
import tarfile
import time
import requests
from PIL import Image, ImageDraw, ImageOps

ROOT = Path(__file__).resolve().parents[1]
BASE_QUOTAS = {
    "test": {"net": 100, "lookalike": 60, "other": 40},
    "val": {"net": 50, "lookalike": 30, "other": 20},
    "train": {"net": 350, "lookalike": 210, "other": 140},
}
FOCUS_QUOTAS = {
    "test": {"net": 50, "lookalike": 60, "other": 90},
    "val": {"net": 50, "lookalike": 40, "other": 10},
    "train": {"net": 400, "lookalike": 200, "other": 100},
}


# 공식 링크에서 중단 후 이어받기가 가능한 다운로드를 합니다.
def download(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    archive = output / "106157.tar.gz"
    partial = output / "106157.tar.gz.part"
    session = requests.Session()
    # 데이터 발행자의 공식 소개 페이지에 있는 실제 압축파일 링크를 찾습니다.
    from bs4 import BeautifulSoup

    response = session.get("https://www.seanoe.org/data/00857/96963/", timeout=40)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    from urllib.parse import urljoin, urlparse

    links = [
        urljoin(response.url, a["href"])
        for a in soup.find_all("a", href=True)
        if a["href"].split("?")[0].endswith("/106157.tar.gz")
    ]
    if not links:
        raise RuntimeError(
            "Official archive link is no longer present; check the dataset landing page."
        )
    url = links[0]
    if urlparse(url).hostname not in (
        "www.seanoe.org",
        "seanoe.org",
        "www.ifremer.fr",
        "data-dataref.ifremer.fr",
    ):
        raise RuntimeError("Unexpected archive host; inspect the official download page.")
    print("OFFICIAL_ARCHIVE", url, flush=True)
    with session.head(url, allow_redirects=True, timeout=40) as head:
        head.raise_for_status()
        size = int(head.headers["Content-Length"])
        metadata = {
            "dataset": "BePLi v2",
            "doi": "10.17882/96963",
            "source_page": "https://www.seanoe.org/data/00858/96963/",
            "download_url": url,
            "license": "CC BY-NC-SA 4.0",
            "license_url": "https://creativecommons.org/licenses/by-nc-sa/4.0/",
            "expected_bytes": size,
            "etag": head.headers.get("ETag"),
            "last_modified": head.headers.get("Last-Modified"),
            "labels": "Publisher-provided manual COCO instance annotations",
            "download_complete": False,
        }
    if archive.exists():
        if archive.stat().st_size != size:
            raise RuntimeError(
                "Existing archive has an unexpected size; preserve it and inspect before retrying."
            )
        print("ARCHIVE_ALREADY_PRESENT", size, flush=True)
    else:
        for attempt in range(4):
            offset = partial.stat().st_size if partial.exists() else 0
            headers = (
                {"Range": f"bytes={offset}-", "Accept-Encoding": "identity"}
                if offset
                else {"Accept-Encoding": "identity"}
            )
            if offset and metadata["etag"]:
                headers["If-Range"] = metadata["etag"]
            try:
                with session.get(url, headers=headers, stream=True, timeout=(30, 120)) as stream:
                    stream.raise_for_status()
                    if offset and (
                        stream.status_code != 206
                        or not stream.headers.get("Content-Range", "").startswith(
                            f"bytes {offset}-"
                        )
                    ):
                        raise RuntimeError(
                            "Server did not honor resume range; preserve partial file and inspect."
                        )
                    if stream.headers.get("Content-Encoding", "identity") != "identity":
                        raise RuntimeError("Unexpected transfer encoding for byte-exact download")
                    start = time.monotonic()
                    last = start
                    with partial.open("ab" if offset else "wb") as target:
                        for chunk in stream.iter_content(4 * 1024 * 1024):
                            if not chunk:
                                continue
                            target.write(chunk)
                            if time.monotonic() - last > 10:
                                done = target.tell()
                                elapsed = max(1, time.monotonic() - start)
                                print(
                                    "DOWNLOAD",
                                    round(done / size * 100, 1),
                                    "percent",
                                    round(done / 1e6),
                                    "MB",
                                    "speed_MB_s",
                                    round((done - offset) / 1e6 / elapsed, 1),
                                    flush=True,
                                )
                                last = time.monotonic()
                if partial.stat().st_size != size:
                    raise requests.ConnectionError("Incomplete transfer")
                partial.rename(archive)
                break
            except requests.RequestException as exc:
                print(
                    "TRANSFER_INTERRUPTED", type(exc).__name__, "attempt", attempt + 1, flush=True
                )
                if attempt == 3:
                    raise
                time.sleep(min(2**attempt, 8))
    print("HASHING_ARCHIVE", flush=True)
    with archive.open("rb") as source:
        metadata["sha256"] = hashlib.file_digest(source, "sha256").hexdigest()
    metadata.update(download_complete=True, actual_bytes=archive.stat().st_size)
    (output / "SOURCE.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "ATTRIBUTION.txt").write_text(
        "Mitsuko Hidaka, Koshiro Murakami, Shintaro Kawahara, Daisuke Sugiyama, Yujin Nakagawa, Shin\u2019ichiro Kako, Daisuke Matsuoka (2023). BePLi Dataset v2: Beach Plastic Litter Dataset version 2. SEANOE. https://doi.org/10.17882/96963\nCC BY-NC-SA 4.0: https://creativecommons.org/licenses/by-nc-sa/4.0/\nOriginal archive downloaded unchanged; derived subsets must document their modifications.\n",
        encoding="utf-8",
    )
    print("DOWNLOAD_COMPLETE", archive, "bytes", archive.stat().st_size, flush=True)


# 압축 안의 경로를 검사하고 중복 원본 폴더는 건너뜁니다.
def extract(archive, output):
    archive, output = Path(archive).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    marker = output / "EXTRACTED.json"
    if marker.exists():
        print(marker.read_text(encoding="utf-8"), flush=True)
        return
    copied, skipped, last = 0, 0, time.monotonic()
    with tarfile.open(archive, "r|gz") as source:
        for member in source:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or any(":" in p for p in path.parts):
                raise ValueError("Unsafe archive member: " + member.name)
            if member.isdir():
                continue
            if not member.isfile():
                raise ValueError("Unexpected link or special archive member: " + member.name)
            if "original_images" in path.parts:
                skipped += 1
                continue
            target = (output / Path(*path.parts)).resolve()
            if not target.is_relative_to(output):
                raise ValueError("Archive path outside destination")
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.extractfile(member) as incoming, target.open("wb") as outgoing:
                shutil.copyfileobj(incoming, outgoing, length=1024 * 1024)
            if target.stat().st_size != member.size:
                raise ValueError("Incomplete file: " + member.name)
            copied += 1
            if time.monotonic() - last > 10:
                print(f"EXTRACTING copied={copied} skipped_originals={skipped}", flush=True)
                last = time.monotonic()
    report = {"archive": str(archive), "copied": copied, "skipped_originals": skipped}
    marker.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("EXTRACTION_COMPLETE", report, flush=True)
    for filename in output.rglob("*.json"):
        if filename == marker:
            continue
        data = json.loads(filename.read_text(encoding="utf-8"))
        if "categories" in data:
            counts = {c["id"]: 0 for c in data["categories"]}
            for ann in data.get("annotations", []):
                counts[ann["category_id"]] += 1
            print(
                "COCO",
                filename,
                "images",
                len(data.get("images", [])),
                "categories",
                [(c["id"], c["name"], counts[c["id"]]) for c in data["categories"]],
                flush=True,
            )


# 비슷한 이미지가 다른 분할에 섞이는지 확인할 작은 해시를 계산합니다.
def difference_hash(image):
    pixels = list(image.convert("L").resize((9, 8)).getdata())
    return sum(
        int(pixels[y * 9 + x] > pixels[y * 9 + x + 1]) << (y * 8 + x)
        for y in range(8)
        for x in range(8)
    )


# 공식 train/val/test 경계를 유지하고 그물 박스를 YOLO 형식으로 씁니다.
def prepare(source, output, quotas=None, retired_test_manifest=None):
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError("Preserve the existing dataset and split: " + str(output))
    rng = random.Random(2027)
    quotas = quotas or BASE_QUOTAS
    retired_ids = set()
    if retired_test_manifest:
        retired_ids = {
            r["source_id"]
            for r in json.loads(Path(retired_test_manifest).read_text(encoding="utf-8"))
            if r["split"] == "test"
        }
    selected, exact, perceptual, inventory, rejected = [], set(), [], {}, Counter()
    # 테스트·검증을 먼저 고르고 겹치는 학습 사진은 제외합니다. 분할 경계를 옮기지 않습니다.
    for split, targets in quotas.items():
        data = json.loads((source / "annotation" / f"{split}.json").read_text(encoding="utf-8"))
        cats = {c["id"]: c["name"] for c in data["categories"]}
        if "fishing_net" not in cats.values():
            raise ValueError("Publisher fishing_net category is missing")
        annotations = defaultdict(list)
        for a in data["annotations"]:
            annotations[a["image_id"]].append(a)
        groups = defaultdict(list)
        for image in data["images"]:
            if split == "test" and image["id"] in retired_ids:
                continue
            anns = annotations[image["id"]]
            nets = [a for a in anns if cats[a["category_id"]] == "fishing_net"]
            group = (
                "net"
                if nets
                else (
                    "lookalike"
                    if any(cats[a["category_id"]] in ("rope", "other_string") for a in anns)
                    else "other"
                )
            )
            path = (source / "images" / split / image["file_name"]).resolve()
            if not path.is_relative_to(source / "images" / split) or not path.is_file():
                raise ValueError("Missing or unsafe source image")
            boxes = []
            for a in nets:
                if a.get("iscrowd", 0) or a.get("ignore", 0):
                    raise ValueError("Unresolved ignored/crowd annotation")
                x, y, w, h = a["bbox"]
                x1, y1 = max(0, x), max(0, y)
                x2, y2 = min(image["width"], x + w), min(image["height"], y + h)
                if x2 <= x1 or y2 <= y1:
                    raise ValueError("Invalid publisher net box")
                boxes.append([x1, y1, x2, y2])
            groups[group].append(
                {
                    "source_id": image["id"],
                    "source_file": str(path),
                    "width": image["width"],
                    "height": image["height"],
                    "split": split,
                    "group": group,
                    "boxes": boxes,
                }
            )
        inventory[split] = {group: len(rows) for group, rows in groups.items()}
        for group, target in targets.items():
            candidates = groups[group]
            rng.shuffle(candidates)
            accepted = 0
            for row in candidates:
                path = Path(row["source_file"])
                with path.open("rb") as source_image:
                    digest = hashlib.file_digest(source_image, "sha256").hexdigest()
                if digest in exact:
                    rejected["exact_duplicate"] += 1
                    continue
                with Image.open(path) as image:
                    if image.size != (row["width"], row["height"]):
                        raise ValueError("Image dimensions differ from COCO metadata")
                    dhash = difference_hash(image)
                if any((dhash ^ previous).bit_count() <= 3 for previous in perceptual):
                    rejected["near_duplicate_dhash_le_3"] += 1
                    continue
                exact.add(digest)
                perceptual.append(dhash)
                row.update(sha256=digest, dhash=f"{dhash:016x}")
                selected.append(row)
                accepted += 1
                if accepted == target:
                    break
            if accepted != target:
                raise ValueError(
                    f"{split}/{group}: {accepted}/{target} unique images; do not fill with search candidates"
                )
        print("SELECTED", split, sum(targets.values()), flush=True)
    if len({r["source_id"] for r in selected}) != len(selected):
        raise ValueError("Source image ID reused across publisher splits")
    for row in selected:
        split = row["split"]
        image_dir, label_dir = output / "images" / split, output / "labels" / split
        image_dir.mkdir(parents=True, exist_ok=True)
        label_dir.mkdir(parents=True, exist_ok=True)
        stem = f"bepli_{row['source_id']:06d}"
        target = image_dir / (stem + ".png")
        shutil.copy2(row["source_file"], target)
        lines = []
        for x1, y1, x2, y2 in row["boxes"]:
            w, h = row["width"], row["height"]
            lines.append(f"0 {(x1+x2)/2/w:.8f} {(y1+y2)/2/h:.8f} {(x2-x1)/w:.8f} {(y2-y1)/h:.8f}")
        (label_dir / (stem + ".txt")).write_text("\n".join(lines), encoding="utf-8")
        row["prepared_file"] = target.relative_to(output).as_posix()
    config = (
        "path: "
        + json.dumps(output.as_posix())
        + "\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n  0: net\n"
    )
    (output / "data.yaml").write_text(config, encoding="utf-8")
    report = {
        "source": "BePLi v2",
        "doi": "10.17882/96963",
        "source_url": "https://doi.org/10.17882/96963",
        "source_license": "CC BY-NC-SA 4.0",
        "labels": "Publisher manual fishing_net COCO boxes",
        "seed": 2027,
        "total": len(selected),
        "train": 700,
        "val": 100,
        "test": 200,
        "development": 800,
        "groups": dict(Counter(r["group"] for r in selected)),
        "split_groups": quotas,
        "inventory": inventory,
        "rejected_duplicates": dict(rejected),
        "retired_test_ids_excluded": sorted(retired_ids),
        "publisher_splits_preserved": True,
        "test_is_held_out": True,
        "duplicate_check": "Original SHA256 and 64-bit dHash Hamming distance <=3; not a guarantee of scene independence",
        "synthetic_images": 0,
        "legacy_search_images": 0,
    }
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (output / "manifest.json").write_text(
        json.dumps(selected, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # 검토용 묶음 사진에는 학습 사진만 넣어 테스트 사진이 튜닝에 쓰이지 않게 합니다.
    review = output / "review"
    review.mkdir()
    train_nets = [r for r in selected if r["split"] == "train" and r["group"] == "net"]
    for sheet_number in range(3):
        sheet = Image.new("RGB", (1080, 680), "#111827")
        draw = ImageDraw.Draw(sheet)
        for index, row in enumerate(train_nets[sheet_number * 12 : (sheet_number + 1) * 12]):
            x, y = index % 3 * 360, index // 3 * 170
            with Image.open(row["source_file"]) as original:
                image = original.convert("RGB")
                overview = ImageOps.contain(image, (178, 142))
                sheet.paste(overview, (x, y + 20))
                scale = overview.width / image.width
                for box in row["boxes"]:
                    draw.rectangle(
                        [
                            x + box[0] * scale,
                            y + 20 + box[1] * scale,
                            x + box[2] * scale,
                            y + 20 + box[3] * scale,
                        ],
                        outline="#22ff88",
                        width=2,
                    )
                largest = max(row["boxes"], key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
                crop = ImageOps.contain(image.crop(tuple(largest)), (178, 142))
                sheet.paste(crop, (x + 180, y + 20))
            draw.text(
                (x + 3, y + 3),
                f"TRAIN {row['source_id']:06d} net x{len(row['boxes'])}",
                fill="white",
            )
        sheet.save(review / f"train_nets_{sheet_number+1}.jpg", quality=90)
    print("DATASET_READY", json.dumps(report), flush=True)


# 학습 사진만 실제 그물 주변으로 자르고 검증·테스트는 원본을 유지합니다.
def focus(source, retired, output):
    source, output = Path(source), Path(output)
    prepare(source, output, FOCUS_QUOTAS, retired)
    data = json.loads((source / "annotation/train.json").read_text(encoding="utf-8"))
    names = {c["id"]: c["name"] for c in data["categories"]}
    annotations = defaultdict(list)
    for ann in data["annotations"]:
        annotations[ann["image_id"]].append(ann)
    rows = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    for row in rows:
        if row["split"] != "train":
            continue
        anns = annotations[row["source_id"]]
        # 사진 종류에 따라 자를 중심 물체를 고릅니다.
        if row["group"] == "net":
            wanted = [a for a in anns if names[a["category_id"]] == "fishing_net"]
        elif row["group"] == "lookalike":
            wanted = [a for a in anns if names[a["category_id"]] in ("rope", "other_string")]
        else:
            wanted = anns
        largest = max(wanted, key=lambda a: a["bbox"][2] * a["bbox"][3]) if wanted else None
        w, h = row["width"], row["height"]
        if largest:
            x, y, bw, bh = largest["bbox"]
            side = max(96, bw * 1.8, bh * 1.8)
            cw, ch = min(w, side), min(h, side)
            left = max(0, min(w - cw, x + bw / 2 - cw / 2))
            top = max(0, min(h - ch, y + bh / 2 - ch / 2))
            right, bottom = left + cw, top + ch
        else:
            left, top, right, bottom = 0, 0, w, h
        left, top, right, bottom = map(round, (left, top, right, bottom))
        nw, nh = right - left, bottom - top
        boxes = []
        for x1, y1, x2, y2 in row["boxes"]:
            box = [max(0, x1 - left), max(0, y1 - top), min(nw, x2 - left), min(nh, y2 - top)]
            if box[2] > box[0] and box[3] > box[1]:
                boxes.append(box)
        if row["group"] == "net" and not boxes:
            raise ValueError("Object-focused crop lost every net label")
        row.update(
            source_boxes=row["boxes"],
            source_width=w,
            source_height=h,
            source_crop=[left, top, right, bottom],
            boxes=boxes,
            width=nw,
            height=nh,
        )
        target = output / row["prepared_file"]
        with Image.open(row["source_file"]) as image:
            image.crop((left, top, right, bottom)).save(target)
        label = output / "labels/train" / (target.stem + ".txt")
        label.write_text(
            "\n".join(
                f"0 {(a+c)/2/nw:.8f} {(b+d)/2/nh:.8f} {(c-a)/nw:.8f} {(d-b)/nh:.8f}"
                for a, b, c, d in boxes
            ),
            encoding="utf-8",
        )
    (output / "manifest.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    report.update(
        training_view="Publisher-object-centered real-image crop, 1.8x context, minimum 96px; no generated photos",
        cropped_training_images=sum(
            r["split"] == "train"
            and r["source_crop"] != [0, 0, r["source_width"], r["source_height"]]
            for r in rows
        ),
        validation_and_test_views="Unchanged full source images",
        previous_baseline_test_retired=True,
    )
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("FOCUSED_REAL_TRAINING_IMAGES_READY", len(rows), flush=True)


# 실행할 데이터 작업을 고릅니다. 기존 데이터 폴더는 덮어쓰지 않습니다.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    download_command = commands.add_parser("download")
    download_command.add_argument("output", type=Path)
    extract_command = commands.add_parser("extract")
    extract_command.add_argument("archive", type=Path)
    extract_command.add_argument("output", type=Path)
    prepare_command = commands.add_parser("prepare")
    prepare_command.add_argument("source", type=Path)
    prepare_command.add_argument("retired_test_manifest", type=Path)
    prepare_command.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.command == "download":
        download(args.output)
    elif args.command == "extract":
        extract(args.archive, args.output)
    else:
        focus(args.source, args.retired_test_manifest, args.output)


if __name__ == "__main__":
    main()
