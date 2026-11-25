"""로컬 조종 사이트를 실행합니다: python main.py --open"""

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import ipaddress
from pathlib import Path
import sys
import webbrowser
from urllib.parse import urlsplit, parse_qs
import requests

ROOT = Path(__file__).resolve().parent
sys.dont_write_bytecode = True


# 같은 주소에서 화면과 카메라·모터 API를 제공합니다.
class Handler(SimpleHTTPRequestHandler):
    # 반복 영상·조종 요청마다 로그 파일이나 긴 접근 기록을 만들지 않습니다.
    def log_message(self, format, *args):
        pass

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


# 영상 수신·그물 추론·모터 통신을 시작합니다.
def control(port, bind, open_browser=False):
    from base64 import b64decode

    from camera import Receiver
    from yolo import Vision
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
    headers = json.loads((ROOT / "jpeg_headers.json").read_text())
    receiver = Receiver(lambda quality: b64decode(headers[str(quality)]))
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



# 실행 옵션만 한곳에서 받습니다. 기본 주소는 기존과 같습니다.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8770)
    parser.add_argument('--bind', default='127.0.0.1')
    parser.add_argument('--open', action='store_true')
    args = parser.parse_args()
    control(args.port, args.bind, args.open)


if __name__ == '__main__':
    main()
