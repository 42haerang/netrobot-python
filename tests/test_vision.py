"""사이트에서 쓸 실제 ONNX를 OpenCV DNN으로 실행하고 JPEG 출력을 확인합니다."""

from pathlib import Path
import sys
import unittest
import threading
from types import SimpleNamespace
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from vision import Detector


class VisionChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.detector = Detector(ROOT / "models")

    def test_real_opencv_inference_and_jpeg_output(self):
        image = np.full((240, 320, 3), 114, dtype=np.uint8)
        ok, jpeg = cv2.imencode(".jpg", image)
        output, result = self.detector.process(jpeg.tobytes())
        decoded = cv2.imdecode(np.frombuffer(output, dtype=np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(decoded.shape, image.shape)
        self.assertEqual(result["engine"], "OpenCV DNN")
        self.assertEqual(result["count"], len(result["boxes"]))
        self.assertGreaterEqual(result["inference_ms"], 0)

    def test_detection_off_and_bad_image(self):
        ok, jpeg = cv2.imencode(".jpg", np.zeros((64, 64, 3), dtype=np.uint8))
        output, result = self.detector.process(jpeg.tobytes(), enabled=False)
        self.assertEqual(result["count"], 0)
        with self.assertRaises(ValueError):
            self.detector.process(b"not a jpeg")

    # 실제 전처리·좌표 복원·OpenCV NMS를 알려진 모델 출력으로 확인합니다.
    def test_letterbox_coordinates_and_nms(self):
        output = np.zeros((1, 5, 8400), dtype=np.float32)
        output[0, :, 0] = (320, 320, 200, 100, 0.9)
        output[0, :, 1] = (320, 320, 200, 100, 0.8)
        detector = Detector.__new__(Detector)
        detector.net = SimpleNamespace(setInput=lambda blob: None, forward=lambda: output)
        detector.lock = threading.Lock()
        boxes = detector.predict(np.zeros((720, 1280, 3), dtype=np.uint8), 0.4)
        self.assertEqual(len(boxes), 1)
        self.assertEqual(boxes[0]["box"], [440, 260, 840, 460])
        output[0, 0, 0] = np.nan
        with self.assertRaises(ValueError):
            detector.predict(np.zeros((720, 1280, 3), dtype=np.uint8), 0.4)
