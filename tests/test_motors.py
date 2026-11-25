"""실물 포트는 열지 않고 명령 확인·활성화·신호 끊김 정지를 검사합니다."""

from pathlib import Path
import sys
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from motors import MotorLink


class FirmwareSerial:
    def __init__(self, *args, **kwargs):
        self.lines = []
        self.reply = b""
        self.stopped = threading.Event()

    def write(self, line):
        text = line.decode().strip()
        self.lines.append(text)
        self.reply = {"HELLO": b"NETROBOT 1\n", "ARM": b"ARMED\n", "STOP": b"STOPPED\n"}.get(
            text, b"OK 90\n"
        )
        if text == "STOP":
            self.stopped.set()

    def readline(self, size):
        reply, self.reply = self.reply, b""
        return reply

    def close(self):
        pass


class MotorsChecks(unittest.TestCase):
    def setUp(self):
        self.link = MotorLink(FirmwareSerial, lambda: [{"port": "TEST"}])
        self.link.connect("TEST")
        self.serial = self.link.serial

    def tearDown(self):
        self.link.disconnect()

    def test_connect_does_not_arm_or_drive(self):
        self.assertTrue(self.link.status()["connected"])
        self.assertFalse(self.link.status()["armed"])
        self.assertNotIn("ARM", self.serial.lines)
        self.assertFalse(any(line.startswith("D ") for line in self.serial.lines))
        with self.assertRaises(RuntimeError):
            self.link.command(0, 0, 0)

    def test_stale_browser_input_stops_and_does_not_rearm(self):
        self.link.arm()
        self.link.command(80, -80, 1)
        self.link.last_input = time.monotonic() - 1
        self.assertTrue(self.serial.stopped.wait(1))
        self.assertFalse(self.link.status()["armed"])
        self.assertEqual(self.link.status()["left"], 0)

    def test_rejects_invalid_output_and_unknown_port(self):
        self.link.arm()
        self.link.command(255, -255, 0)
        self.assertEqual(self.link.values, (255, -255, 0))
        for values in ((256, 0, 0), (0, -256, 0), (True, 0, 0), (0, 0, 2)):
            with self.assertRaises(ValueError):
                self.link.command(*values)
        with self.assertRaises(ValueError):
            self.link.connect("OTHER")

    # USB는 HC-06과 다른 115200 속도를 쓰며 연결만으로 활성화되지 않습니다.
    def test_usb_connection_uses_usb_baud_without_arming(self):
        opened = []

        def opener(port, baud, **options):
            opened.append((port, baud))
            return FirmwareSerial()

        link = MotorLink(opener, lambda: [{"port": "USB_TEST", "transport": "usb", "baud": 115200}])
        try:
            link.connect("USB_TEST")
            self.assertEqual(opened, [("USB_TEST", 115200)])
            self.assertEqual(link.status()["transport"], "usb")
            self.assertFalse(link.status()["armed"])
        finally:
            link.disconnect()
