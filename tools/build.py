"""미리보기, APK 빌드, GitHub Release 업로드 도구입니다."""

import argparse
from functools import partial
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import ipaddress
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import webbrowser
from urllib.parse import urlsplit, parse_qs
import requests

ROOT = Path(__file__).resolve().parents[1]
REPO = "42haerang/netrobot-python"
API = f"https://api.github.com/repos/{REPO}"


# Python 코드의 해시를 HTML에 기록해 온라인 화면과 코드가 맞는지 확인합니다.
def stamp_screen():
    path = ROOT / "web/index.html"
    code_path = ROOT / "web/app.py"
    code = code_path.read_bytes().replace(b"\r\n", b"\n")
    code_path.write_bytes(code)
    digest = hashlib.sha256(code).hexdigest()
    html = path.read_text(encoding="utf-8")
    html = re.sub(r'\s*<meta name="netrobot-python-sha256" content="[0-9a-f]+">', "", html)
    html = re.sub(
        r'(<meta name="netrobot-ui-version" content="\d+">)',
        lambda match: match[1]
        + "\n  "
        + f'<meta name="netrobot-python-sha256" content="{digest}">',
        html,
    )
    path.write_text(html, encoding="utf-8", newline="\n")


# 화면과 검증된 그물 모델을 APK 자원 폴더에 복사합니다.
def prepare():
    stamp_screen()
    assets = ROOT / "android/app/src/main/assets"
    shutil.copytree(
        ROOT / "web",
        assets / "web",
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    models = assets / "web/models"
    models.mkdir(exist_ok=True)
    source = ROOT / "models"
    info = (
        json.loads((source / "model.json").read_text(encoding="utf-8"))
        if (source / "model.json").is_file()
        else {}
    )
    ready = (
        info.get("trained_on_net") is True
        and info.get("validated_for_bundle") is True
        and info.get("names") in (["net"], ["fishing_net"])
        and (source / "net.onnx").is_file()
    )
    if info.get("trained_on_net") is True and not ready:
        raise RuntimeError(
            "Net weights need successful evaluation and runtime checks before bundling; download the validated Release weights if missing."
        )
    if ready:
        with (source / "net.onnx").open("rb") as model_file:
            digest = hashlib.file_digest(model_file, "sha256").hexdigest()
        if digest != info.get("sha256"):
            raise RuntimeError("The net model does not match its export metadata SHA256")
        shutil.copy2(source / "net.onnx", models / "net.onnx")
        for name in ("MODEL_CARD.md", "ATTRIBUTION.txt"):
            if (source / name).is_file():
                shutil.copy2(source / name, models / name)
        info.update(available=True, file="net.onnx")
    else:
        # Never silently relabel a COCO demo or synthetic fixture as a fishing-net model.
        if (models / "net.onnx").exists():
            raise RuntimeError(
                "Stale bundled model exists; inspect it before building without net weights."
            )
        info = {
            "available": False,
            "trained_on_net": False,
            "status": "Publisher-labeled net training is not complete.",
        }
    (models / "model.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("Offline APK assets ready. Net-trained model included:", ready)


# 정적 화면과 로컬 카메라·OpenCV·모터 API를 같은 서버에서 제공합니다.
class Handler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".js": "text/javascript",
        ".mjs": "text/javascript",
        ".wasm": "application/wasm",
    }

    # 다른 웹사이트가 이 노트북의 카메라나 모터를 조작하지 못하게 합니다.
    def local_request(self):
        host = self.headers.get("Host", "").split(":")[0]
        try:
            valid_host = host == "localhost" or ipaddress.ip_address(host).is_private
        except ValueError:
            valid_host = False
        origin = self.headers.get("Origin")
        return (
            valid_host
            and self.headers.get("Sec-Fetch-Site") not in ("cross-site", "same-site")
            and (not origin or origin == "http://" + self.headers.get("Host"))
        )

    def do_GET(self):
        parsed = urlsplit(self.path)
        if not parsed.path.startswith("/native/"):
            return super().do_GET()
        if not self.local_request():
            return self.answer({"error": "같은 로컬 조종 페이지에서 연결하세요."}, 403)
        receiver = getattr(self.server, "receiver", None)
        vision = getattr(self.server, "vision", None)
        motors = getattr(self.server, "motors", None)
        query = parse_qs(parsed.query)
        try:
            if parsed.path == "/native/motor/ports":
                return self.answer({"ports": motors.ports() if motors else []})
            if parsed.path == "/native/motor/status":
                return self.answer(
                    motors.status()
                    if motors
                    else {
                        "connected": False,
                        "armed": False,
                        "error": "Python 모터 수신부가 필요합니다.",
                    }
                )
            if receiver is None:
                return self.answer({"error": "Python 수신부가 실행 중이지 않습니다."}, 503)
            if parsed.path == "/native/connect":
                receiver.connect(
                    query.get("host", ["192.168.169.1"])[0], query.get("mode", ["zigzag"])[0]
                )
                return self.answer({"ok": True})
            if parsed.path == "/native/disconnect":
                receiver.close()
                return self.answer({"ok": True})
            if parsed.path == "/native/status":
                return self.answer(
                    {
                        **receiver.status(),
                        "site_source": "python",
                        "service": "netrobot-flow",
                        "vision": (
                            vision.status()
                            if vision
                            else {"ready": False, "has_frame": False, "error": "OpenCV 준비 전"}
                        ),
                    }
                )
            if parsed.path == "/native/vision/frame.jpg":
                frame = vision.frame() if vision else None
            elif parsed.path == "/native/frame.jpg":
                frame, sequence = receiver.frame()
            else:
                return self.answer({"error": "없는 경로입니다."}, 404)
            if frame is None:
                return self.answer({"error": "아직 새 영상이 없습니다."}, 503)
            return self.answer(frame, mime="image/jpeg")
        except Exception as error:
            return self.answer({"error": str(error)}, 400)

    # 실제 모터 명령은 JSON POST로만 받습니다. 브라우저 외부 페이지 요청은 거부합니다.
    def do_POST(self):
        if not self.local_request():
            return self.answer({"error": "같은 로컬 조종 페이지에서 연결하세요."}, 403)
        path = urlsplit(self.path).path
        try:
            length = int(self.headers.get("Content-Length", "0"))
            limit = 4 * 1024 * 1024 if path == "/native/vision/detect" else 4096
            if not 0 < length <= limit:
                raise ValueError("요청 크기를 확인하세요.")
            body = self.rfile.read(length)
            vision, motors = getattr(self.server, "vision", None), getattr(
                self.server, "motors", None
            )
            if path == "/native/vision/detect":
                if vision is None:
                    raise RuntimeError("OpenCV 수신부를 먼저 실행하세요.")
                image, result = vision.process(body)
                return self.answer(
                    image,
                    mime="image/jpeg",
                    headers={
                        "X-Net-Count": str(result["count"]),
                        "X-Inference-Ms": str(result["inference_ms"]),
                    },
                )
            if self.headers.get_content_type() != "application/json":
                raise ValueError("JSON 명령이 필요합니다.")
            data = json.loads(body)
            if not isinstance(data, dict):
                raise ValueError("명령 형식이 잘못되었습니다.")
            if path == "/native/vision/config":
                if vision is None:
                    raise RuntimeError("OpenCV 수신부를 먼저 실행하세요.")
                vision.configure(data.get("enabled"), data.get("threshold"))
                return self.answer(vision.status())
            if motors is None:
                raise RuntimeError("Python 모터 수신부를 먼저 실행하세요.")
            if path == "/native/motor/connect":
                motors.connect(data.get("port", ""))
            elif path == "/native/motor/arm":
                motors.arm()
            elif path == "/native/motor/stop":
                motors.stop()
            elif path == "/native/motor/disconnect":
                motors.disconnect()
            elif path == "/native/motor/command":
                motors.command(data.get("left"), data.get("right"), data.get("grip"))
            else:
                return self.answer({"error": "없는 경로입니다."}, 404)
            return self.answer(motors.status())
        except Exception as error:
            return self.answer({"error": str(error)}, 400)

    # JPEG와 JSON을 명확한 길이로 돌려주고 프레임은 브라우저 캐시에 남기지 않습니다.
    def answer(self, value, status=200, mime="application/json", headers=None):
        body = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        for key, value in {
            "Content-Type": mime,
            "Content-Length": str(len(body)),
            "Cache-Control": "no-store",
            **(headers or {}),
        }.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)


# APK 없이 Python으로 드론 영상을 받고 같은 웹 조종 화면을 제공합니다.
def control(port, bind, open_browser=False):
    from base64 import b64decode

    sys.path.insert(0, str(ROOT / "android/app/src/main/python"))
    from flow_video import Receiver
    from vision import Vision
    from motors import MotorLink

    url = f"http://127.0.0.1:{port}/?bridge=1"
    # 바로가기를 두 번 눌러도 기존 조종 화면만 다시 엽니다.
    if open_browser:
        try:
            status = requests.get(f"http://127.0.0.1:{port}/native/status", timeout=1).json()
            if status.get("service") == "netrobot-flow":
                webbrowser.open(url)
                return
        except (requests.RequestException, ValueError):
            pass
    headers = json.loads((ROOT / "android/app/src/main/assets/jpeg_headers.json").read_text())
    receiver = Receiver(lambda quality: b64decode(headers[str(quality)]))
    stamp_screen()
    server = ThreadingHTTPServer((bind, port), partial(Handler, directory=str(ROOT / "web")))
    server.receiver = receiver
    server.vision = Vision(receiver, ROOT / "models")
    server.motors = MotorLink()
    print(f"브라우저 조종: {url}", flush=True)
    if open_browser:
        webbrowser.open(url)
    if bind != "127.0.0.1":
        print(f"휴대폰: http://<이 기기의 Wi-Fi IP>:{port}/?bridge=1", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.motors.disconnect()
        server.vision.close()
        receiver.close()
        server.server_close()


# 같은 코드를 브라우저에서 가볍게 실행해 볼 수 있습니다.
def preview(port):
    stamp_screen()
    print(f"http://127.0.0.1:{port}", flush=True)
    server = ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, directory=str(ROOT / "web")))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


# Android의 표준 Gradle 도구로 빌드하고 결과 파일의 해시도 함께 저장합니다.
def apk():
    prepare()
    wrapper = ROOT / "android" / ("gradlew.bat" if os.name == "nt" else "gradlew")
    subprocess.run(
        [str(wrapper), "-p", str(ROOT / "android"), ":app:assembleDebug", "--console=plain"],
        check=True,
    )
    output = ROOT / "NetRobot-Drone-v0.3.0.apk"
    shutil.copy2(ROOT / "android/app/build/outputs/apk/debug/app-debug.apk", output)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(".apk.sha256").write_text(digest + "  " + output.name + "\n")
    print(output, flush=True)


# 기존 Git 자격 증명은 메모리에서만 사용하고 토큰은 출력하거나 저장하지 않습니다.
def publish(tag, commit, body_file, assets):
    credential = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n",
        text=True,
        capture_output=True,
        check=True,
        env={**os.environ, "GCM_INTERACTIVE": "never", "GIT_TERMINAL_PROMPT": "0"},
    )
    fields = dict(line.split("=", 1) for line in credential.stdout.splitlines() if "=" in line)
    token = fields.get("password")
    if not token:
        raise RuntimeError("No existing GitHub credential; no credentials printed")
    # 같은 GitHub 저장소의 Release API에만 기존 인증을 전달합니다.
    session = requests.Session()
    session.headers.update(
        {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
    )
    # 공개한 버전은 수정하지 않고 새 초안에 모든 파일을 먼저 올립니다.
    existing = session.get(API + "/releases", params={"per_page": 100}, timeout=30)
    existing.raise_for_status()
    release = next((r for r in existing.json() if r["tag_name"] == tag), None)
    if release and not release["draft"]:
        raise RuntimeError("Preserve the already published release; use a new version")
    body = Path(body_file).read_text(encoding="utf-8")
    if release is None:
        created = session.post(
            API + "/releases",
            json={
                "tag_name": tag,
                "target_commitish": commit,
                "name": "NetRobot Drone " + tag.removeprefix("android-"),
                "body": body,
                "draft": True,
                "prerelease": True,
            },
            timeout=30,
        )
        created.raise_for_status()
        release = created.json()
    # 업로드 전후 크기와 SHA256이 같은지 확인해 불완전한 파일 공개를 막습니다.
    existing_assets = {a["name"]: a for a in release["assets"]}
    for filename in assets:
        path = Path(filename)
        with path.open("rb") as content:
            digest = hashlib.file_digest(content, "sha256").hexdigest()
        if path.name in existing_assets:
            asset = existing_assets[path.name]
            if asset["size"] != path.stat().st_size or asset.get("digest") != "sha256:" + digest:
                raise RuntimeError(
                    "Existing draft asset differs; preserve and inspect: " + path.name
                )
            print("ASSET_ALREADY_PRESENT", path.name, flush=True)
            continue
        with path.open("rb") as content:
            uploaded = session.post(
                release["upload_url"].split("{")[0],
                params={"name": path.name},
                data=content,
                headers={"Content-Type": "application/octet-stream"},
                timeout=(30, 600),
            )
        uploaded.raise_for_status()
        asset = uploaded.json()
        if asset["size"] != path.stat().st_size or asset.get("digest") != "sha256:" + digest:
            raise RuntimeError("Uploaded size or SHA256 differs: " + path.name)
        print("ASSET_VERIFIED", path.name, asset["size"], flush=True)
    # 모든 파일이 확인된 경우에만 초안을 공개합니다.
    response = session.patch(
        API + f"/releases/{release['id']}",
        json={"draft": False, "body": body, "make_latest": "false"},
        timeout=30,
    )
    response.raise_for_status()
    print("PUBLIC_RELEASE", response.json()["html_url"], flush=True)


# 비슷한 실행 명령을 한 파일의 하위 명령으로 모았습니다.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    preview_command = commands.add_parser("preview")
    preview_command.add_argument("--port", type=int, default=8765)
    control_command = commands.add_parser("control")
    control_command.add_argument("--port", type=int, default=8765)
    control_command.add_argument("--bind", default="127.0.0.1")
    control_command.add_argument("--open", action="store_true")
    commands.add_parser("prepare")
    commands.add_parser("apk")
    publishing = commands.add_parser("publish")
    publishing.add_argument("--tag", required=True)
    publishing.add_argument("--commit", required=True)
    publishing.add_argument("--body", required=True, type=Path)
    publishing.add_argument("assets", nargs="+", type=Path)
    args = parser.parse_args()
    if args.command == "preview":
        preview(args.port)
    elif args.command == "control":
        control(args.port, args.bind, args.open)
    elif args.command == "prepare":
        prepare()
    elif args.command == "apk":
        apk()
    else:
        publish(args.tag, args.commit, args.body, args.assets)


if __name__ == "__main__":
    main()
