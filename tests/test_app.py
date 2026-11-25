"""조종 계산, 실제 YOLO 좌표 변환, APK 사이트 주소 제한을 검사합니다."""

import ast
import json
import importlib.util
import hashlib
import io
from pathlib import Path, PurePosixPath
import unittest
import re
import threading
import http.client
from http.server import ThreadingHTTPServer
from functools import partial
import time
import sys
from types import SimpleNamespace
from urllib.parse import urlsplit, unquote

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("web_app", ROOT / "web/app.py")
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


# Android가 없는 PC에서도 실제 주소 검사 함수만 가져와 검사합니다.
source = ast.parse(
    (ROOT / "android/app/src/main/python/drone_android.py").read_text(encoding="utf-8")
)
function = next(
    node for node in source.body if isinstance(node, ast.FunctionDef) and node.name == "site_path"
)
namespace = {
    "urlsplit": urlsplit,
    "unquote": unquote,
    "PurePosixPath": PurePosixPath,
    "SITE": "https://42haerang.github.io/netrobot-python/",
}
exec(compile(ast.Module(body=[function], type_ignores=[]), "site_path", "exec"), namespace)

# WebView 없이도 실제 화면 선택 함수의 온라인·오프라인 동작을 실행합니다.
client = next(
    node for node in source.body if isinstance(node, ast.ClassDef) and node.name == "Client"
)
loader = next(
    node for node in client.body if isinstance(node, ast.FunctionDef) and node.name == "load_screen"
)
screen_namespace = {"SITE": namespace["SITE"], "hashlib": hashlib, "re": re}
exec(compile(ast.Module(body=[loader], type_ignores=[]), "load_screen", "exec"), screen_namespace)


class AppChecks(unittest.TestCase):
    # 정상 GitHub 화면만 함께 적용하고 코드 불일치나 인터넷 끊김은 사본을 씁니다.
    def test_online_screen_pair_and_offline_fallback(self):
        code = b'print("python screen")'
        digest = hashlib.sha256(code).hexdigest()
        html = (
            '<meta name="netrobot-ui-version" content="3">'
            + f'<meta name="netrobot-python-sha256" content="{digest}">'
        ).encode()
        for mode in ("online", "mismatch", "offline"):

            def open_url(url, timeout):
                if mode == "offline":
                    raise OSError("No internet")
                if url.endswith("index.html"):
                    return io.BytesIO(html)
                return io.BytesIO(code if mode == "online" else b"wrong version")

            screen_namespace["urlopen"] = open_url
            owner = SimpleNamespace(
                screen=None, screen_lock=threading.Lock(), screen_source="offline"
            )
            screen_namespace["load_screen"](owner)
            self.assertEqual(owner.screen_source, "github" if mode == "online" else "offline")
            self.assertEqual(bool(owner.screen), mode == "online")

    # 손잡이를 놓았을 때 정지하고 전진·회전 시 네 바퀴 방향이 맞아야 합니다.
    def test_joystick_and_four_wheels(self):
        self.assertEqual(app.joystick_vector(0, 0, 50), (0, 0))
        self.assertEqual(app.joystick_vector(0, -100, 50), (0, 1))
        self.assertEqual(app.wheel_values(0, 1), [1, 1, 1, 1])
        self.assertEqual(app.wheel_values(1, 0), [1, 1, -1, -1])
        with self.assertRaises(ValueError):
            app.wheel_values(float("nan"), 0)

    # 1280×720 영상의 회색 여백을 제거하고 중복 박스를 한 개로 줄여야 합니다.
    def test_yolo_letterbox_nms_and_invalid_values(self):
        count = 8400
        data = [0.0] * (5 * count)
        for index, score in ((0, 0.9), (1, 0.8), (2, 0.2)):
            for channel, value in enumerate((320, 320, 200, 100, score)):
                data[channel * count + index] = value
        boxes = app.decode_yolo(data, [1, 5, count], 1280, 720)
        self.assertEqual(len(boxes), 1)
        self.assertEqual(boxes[0]["box"], [440, 260, 840, 460])
        data[0] = float("nan")
        self.assertEqual(app.decode_yolo(data, [1, 5, count], 1280, 720)[0]["score"], 0.8)
        with self.assertRaises(ValueError):
            app.decode_yolo([], [1, 84, count], 1280, 720)

    # 다른 GitHub 프로젝트나 인코딩된 상위 폴더에는 영상 API를 열지 않습니다.
    def test_native_site_boundary(self):
        path = namespace["site_path"]
        base = namespace["SITE"]
        self.assertEqual(path(base + "?app=1"), "index.html")
        self.assertEqual(path(base + "native/status"), "native/status")
        for url in (
            base + "%2e%2e/private",
            base + "a%5cb",
            base.replace("https:", "http:"),
            "https://42haerang.github.io/other/native/status",
            "https://42haerang.github.io.evil.test/netrobot-python/",
        ):
            self.assertIsNone(path(url))


# 실제 HTTP 요청으로 Python 영상 수신부의 상태·오류·접근 제한을 확인합니다.
class BridgeChecks(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(ROOT / "android/app/src/main/python"))
        from flow_video import Receiver

        spec = importlib.util.spec_from_file_location("build_tool", ROOT / "tools/build.py")
        build = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(build)
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0), partial(build.Handler, directory=str(ROOT / "web"))
        )
        self.server.receiver = Receiver(lambda quality: b"")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.server.receiver.close()
        self.thread.join()

    def get(self, path, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        connection.request("GET", path, headers=headers or {})
        response = connection.getresponse()
        status, body = response.status, response.read()
        connection.close()
        return status, body

    def test_status_frames_and_private_drone_address(self):
        status, body = self.get("/native/status")
        self.assertEqual(status, 200)
        self.assertFalse(json.loads(body)["ready"])
        self.assertEqual(self.get("/native/frame.jpg")[0], 503)
        self.assertEqual(self.get("/native/connect?host=8.8.8.8")[0], 400)
        self.server.receiver.jpeg = b"camera-frame"
        self.server.receiver.timestamp = time.monotonic()
        self.assertEqual(self.get("/native/frame.jpg"), (200, b"camera-frame"))

    def test_other_sites_cannot_read_camera(self):
        self.assertEqual(self.get("/native/status", {"Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertEqual(self.get("/native/status", {"Host": "evil.example"})[0], 403)


if __name__ == "__main__":
    unittest.main()
