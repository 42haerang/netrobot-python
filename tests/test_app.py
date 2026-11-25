"""조종 계산, 실제 HTTP 영상·모터 API을 검사합니다."""

import json
import importlib.util
from pathlib import Path
import unittest
import threading
import http.client
from http.server import ThreadingHTTPServer
from functools import partial
import time
import sys

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("web_app", ROOT / "web/app.py")
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


class AppChecks(unittest.TestCase):
    # 손잡이를 놓았을 때 정지하고 전진·회전 시 앞바퀴 두 개의 방향이 맞아야 합니다.
    def test_joystick_and_two_front_wheels(self):
        self.assertEqual(app.joystick_vector(0, 0, 50), (0, 0))
        self.assertEqual(app.joystick_vector(0, -100, 50), (0, 1))
        self.assertEqual(app.wheel_values(0, 1), [1, 1])
        self.assertEqual(app.wheel_values(1, 0), [1, -1])
        with self.assertRaises(ValueError):
            app.wheel_values(float("nan"), 0)

# 실제 HTTP 요청으로 Python 영상 수신부의 상태·오류·접근 제한을 확인합니다.
class BridgeChecks(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(ROOT))
        from camera import Receiver

        spec = importlib.util.spec_from_file_location("build_tool", ROOT / "main.py")
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

    # 실제 HTTP 경로를 가상 포트에 연결해 활성화·명령·정지와 외부 요청 거부를 검사합니다.
    def test_motor_http_controls_and_origin_boundary(self):
        from test_motors import FirmwareSerial, MotorLink

        link = MotorLink(FirmwareSerial, lambda: [{"port": "TEST"}])
        self.server.motors = link

        def post(action, data, origin=None):
            connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
            headers = {"Content-Type": "application/json"}
            if origin:
                headers["Origin"] = origin
            connection.request("POST", "/native/motor/" + action, json.dumps(data), headers)
            response = connection.getresponse()
            status, body = response.status, json.loads(response.read())
            connection.close()
            return status, body

        try:
            self.assertEqual(post("connect", {"port": "TEST"})[0], 200)
            self.assertFalse(link.status()["armed"])
            self.assertEqual(post("command", {"left": 80, "right": 80, "grip": 0})[0], 400)
            self.assertEqual(post("arm", {}, "https://evil.example")[0], 403)
            self.assertFalse(link.status()["armed"])
            self.assertTrue(post("arm", {})[1]["armed"])
            self.assertEqual(post("command", {"left": 80, "right": -80, "grip": 1})[0], 200)
            self.assertEqual(link.values, (80, -80, 1))
            self.assertEqual(post("command", {"left": 999, "right": 0, "grip": 0})[0], 400)
            self.assertFalse(post("stop", {})[1]["armed"])
            self.assertEqual(link.values, (0, 0, 0))
        finally:
            link.disconnect()


if __name__ == "__main__":
    unittest.main()
