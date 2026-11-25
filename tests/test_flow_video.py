"""Protocol tests use generated JPEGs and UDP fragments; no drone commands are sent."""

import io
import json
from base64 import b64decode
from pathlib import Path
import struct
import sys
import unittest
import threading
from unittest.mock import patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from camera import Frames, parse_fragment, Receiver


def header(q):
    path = ROOT / "jpeg_headers.json"
    return b64decode(json.loads(path.read_text())[str(q)])


def packet(seq, index, total, body, width=64, height=32, q=50):
    p = bytearray(56)
    p[:2] = b"\x93\x01"
    part = body[index * 1024 : (index + 1) * 1024]
    struct.pack_into("<H", p, 2, 56 + len(part))
    struct.pack_into("<Q", p, 8, seq)
    struct.pack_into("<IIIHHB", p, 32, index, total, len(body), width, height, q)
    return bytes(p) + part


class FlowProtocol(unittest.TestCase):
    # Wi-Fi 전환 중 소켓 생성이 실패해도 다음 시도까지 수신기가 살아 있어야 합니다.
    def test_retry_after_network_failure(self):
        receiver = Receiver(header)
        stop = threading.Event()
        attempts = []

        def unavailable_socket(*args):
            attempts.append(1)
            if len(attempts) == 2:
                stop.set()
            raise OSError("network temporarily unavailable")

        with patch("camera.socket.socket", side_effect=unavailable_socket):
            receiver._run("192.168.169.1", "zigzag", stop)
        self.assertEqual(len(attempts), 2)

    def test_reordered_duplicate_fragments_and_real_jpeg_decode(self):
        from PIL import Image

        rng = np.random.default_rng(2027)
        rgb = rng.integers(0, 256, (32, 64, 3), dtype=np.uint8)
        out = io.BytesIO()
        Image.fromarray(rgb).save(out, format="JPEG", quality=50, subsampling=0, optimize=False)
        original = out.getvalue()
        pos = 2
        while original[pos + 1] != 0xDA:
            pos += 2 + int.from_bytes(original[pos + 2 : pos + 4], "big")
        start = pos + 2 + int.from_bytes(original[pos + 2 : pos + 4], "big")
        body = original[start:-2]
        total = (len(body) + 1023) // 1024
        frames = Frames(header)
        image = None
        for i in reversed(range(total)):
            result = frames.add(packet(1, i, total, body), now=10)
            image = result or image
            frames.add(packet(1, i, total, body), now=10)
        self.assertIsNotNone(image)
        actual = cv2.imdecode(np.frombuffer(image, np.uint8), cv2.IMREAD_COLOR)
        expected = cv2.imdecode(np.frombuffer(original, np.uint8), cv2.IMREAD_COLOR)
        np.testing.assert_array_equal(actual, expected)
        acknowledgement = frames.acknowledgement(now=10.1)
        self.assertEqual(acknowledgement[:2], b"\xef\x02")
        self.assertEqual(acknowledgement[12:82], bytes(70))
        self.assertEqual(struct.unpack_from("<H", acknowledgement, 2)[0], len(acknowledgement))
        self.assertEqual(struct.unpack_from("<I", acknowledgement, 8)[0], 2)

    def test_reject_invalid_lengths_dimensions_and_fragment_indexes(self):
        valid = packet(1, 0, 1, b"abc")
        self.assertIsNotNone(parse_fragment(valid))
        self.assertIsNone(parse_fragment(valid[:-1]))
        self.assertIsNone(parse_fragment(packet(0, 0, 1, b"abc")))
        self.assertIsNone(parse_fragment(packet(1, 0, 1, b"abc", width=0)))
        malformed = bytearray(valid)
        struct.pack_into("<I", malformed, 32, 1)
        self.assertIsNone(parse_fragment(malformed))
        frames = Frames(header)
        self.assertIsNone(frames.add(bytes(malformed)))


if __name__ == "__main__":
    unittest.main()
