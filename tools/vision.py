"""OpenCV로 JPEG를 읽고 YOLO 그물 추론·박스 표시·JPEG 출력을 합니다."""

import hashlib
import json
import math
from pathlib import Path
import threading
import time

import cv2
import numpy as np


# ONNX는 모델 파일 형식이며 실제 계산은 OpenCV DNN의 CPU 엔진이 수행합니다.
class Detector:
    def __init__(self, folder):
        folder = Path(folder)
        info = json.loads((folder / "model.json").read_text(encoding="utf-8"))
        model = folder / "net.onnx"
        if hashlib.sha256(model.read_bytes()).hexdigest() != info["sha256"]:
            raise ValueError("그물 모델 SHA256이 모델 설명과 다릅니다.")
        if info.get("names") != ["net"] or info.get("size") != 640:
            raise ValueError("640 입력의 그물 한 종류 모델이 필요합니다.")
        cv2.setNumThreads(2)
        self.net = cv2.dnn.readNetFromONNX(str(model))
        self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        self.lock = threading.Lock()

    # 긴 변을 640에 맞추고 회색 여백을 넣어 학습 때와 입력 조건을 맞춥니다.
    def predict(self, image, threshold):
        height, width = image.shape[:2]
        scale = min(640 / width, 640 / height)
        nw, nh = math.floor(width * scale + 0.5), math.floor(height * scale + 0.5)
        left, top = (640 - nw) // 2, (640 - nh) // 2
        canvas = np.full((640, 640, 3), 114, dtype=np.uint8)
        canvas[top : top + nh, left : left + nw] = cv2.resize(image, (nw, nh))
        blob = cv2.dnn.blobFromImage(canvas, 1 / 255, (640, 640), swapRB=True, crop=False)
        with self.lock:
            self.net.setInput(blob)
            output = self.net.forward()
        if output.shape != (1, 5, 8400) or not np.isfinite(output).all():
            raise ValueError("그물 모델 출력 형식이나 숫자가 올바르지 않습니다.")

        # 회색 여백을 제거해 원본 영상 좌표로 되돌리고 겹치는 후보를 줄입니다.
        boxes, scores = [], []
        for cx, cy, bw, bh, score in output[0].T:
            if score < threshold:
                continue
            x1, y1 = max(0, (cx - bw / 2 - left) / scale), max(0, (cy - bh / 2 - top) / scale)
            x2, y2 = min(width, (cx + bw / 2 - left) / scale), min(
                height, (cy + bh / 2 - top) / scale
            )
            if x2 > x1 and y2 > y1:
                boxes.append([float(x1), float(y1), float(x2 - x1), float(y2 - y1)])
                scores.append(float(score))
        selected = cv2.dnn.NMSBoxes(boxes, scores, threshold, 0.45)
        result = []
        for index in np.asarray(selected).reshape(-1)[:40]:
            x, y, w, h = boxes[int(index)]
            result.append({"box": [x, y, x + w, y + h], "score": scores[int(index)]})
        return result

    # 박스와 신뢰도를 OpenCV로 그립니다. 브라우저는 완성된 JPEG만 표시합니다.
    def process(self, jpeg, threshold=0.4, enabled=True):
        image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None or max(image.shape[:2]) > 4096:
            raise ValueError("4096px 이하의 올바른 영상 프레임이 필요합니다.")
        start = time.monotonic()
        boxes = self.predict(image, threshold) if enabled else []
        elapsed = round((time.monotonic() - start) * 1000)
        for item in boxes:
            x1, y1, x2, y2 = map(round, item["box"])
            cv2.rectangle(image, (x1, y1), (x2, y2), (60, 230, 100), 2)
            label = f"NET {round(item['score']*100)}%"
            cv2.putText(
                image,
                label,
                (x1, max(18, y1 - 7)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (60, 230, 100),
                2,
            )
        ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            raise RuntimeError("OpenCV JPEG 변환에 실패했습니다.")
        return encoded.tobytes(), {
            "count": len(boxes),
            "boxes": boxes,
            "inference_ms": elapsed,
            "width": image.shape[1],
            "height": image.shape[0],
            "engine": "OpenCV DNN",
        }


# 수신기와 추론을 분리하고 최신 프레임 한 장만 처리해 지연이 쌓이지 않게 합니다.
class Vision:
    def __init__(self, receiver, folder):
        self.receiver = receiver
        self.lock = threading.Lock()
        self.enabled, self.threshold, self.revision = True, 0.4, 0
        self.jpeg = None
        self.result = {}
        self.timestamp = 0
        self.error = ""
        self.stop_event = threading.Event()
        try:
            self.detector = Detector(folder)
        except Exception as error:
            self.detector = None
            self.error = str(error)
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    # 설정이 바뀌면 이전 박스 이미지를 버리고 현재 프레임을 다시 처리합니다.
    def configure(self, enabled, threshold):
        if (
            type(enabled) is not bool
            or not isinstance(threshold, (float, int))
            or not 0.1 <= threshold <= 0.9
        ):
            raise ValueError("감지 설정 범위를 확인하세요.")
        with self.lock:
            if (enabled, threshold) != (self.enabled, self.threshold):
                self.enabled, self.threshold = enabled, threshold
                self.revision += 1
                self.jpeg = None

    # 사진·영상 파일에서 보낸 프레임도 같은 OpenCV 코드로 처리합니다.
    def process(self, jpeg):
        if self.detector is None:
            raise RuntimeError(self.error or "OpenCV 모델이 준비되지 않았습니다.")
        with self.lock:
            enabled, threshold = self.enabled, self.threshold
        return self.detector.process(jpeg, threshold, enabled)

    def run(self):
        last = None
        while not self.stop_event.wait(0.03):
            jpeg, sequence = self.receiver.frame()
            with self.lock:
                revision = self.revision
            if jpeg is None or self.detector is None or last == (sequence, revision):
                continue
            try:
                image, result = self.process(jpeg)
                with self.lock:
                    if revision == self.revision:
                        self.jpeg, self.result, self.timestamp = image, result, time.monotonic()
                        self.error = ""
                last = sequence, revision
            except Exception as error:
                with self.lock:
                    self.error = str(error)
            self.stop_event.wait(0.1)

    # 오래된 감지 이미지는 연결된 영상처럼 계속 내보내지 않습니다.
    def frame(self):
        with self.lock:
            return self.jpeg if time.monotonic() - self.timestamp < 1.5 else None

    def status(self):
        with self.lock:
            return {
                **self.result,
                "engine": "OpenCV DNN",
                "ready": self.detector is not None,
                "has_frame": self.jpeg is not None and time.monotonic() - self.timestamp < 1.5,
                "enabled": self.enabled,
                "threshold": self.threshold,
                "error": self.error,
            }

    def close(self):
        self.stop_event.set()
        self.thread.join(timeout=2)
