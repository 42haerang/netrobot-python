# 외부 구성요소

- Brython 3.15.0: https://github.com/brython-dev/brython · BSD-3-Clause. 브라우저에서 Python을 실행합니다. `web/vendor/BRYTHON-LICENSE.txt`와 `brython-version.json`에 라이선스·원본 주소·패키지 SHA256을 기록합니다.
- OpenCV: https://opencv.org/ · Apache-2.0. 현재 영상 디코딩·전처리·YOLO DNN·NMS·박스 표시·JPEG 출력에 사용합니다. 이전 ONNX Runtime Web 배포본은 Git 이력에 보존하고 현재 웹 실행 경로에서 제거했습니다.
- pySerial 3.5: https://pyserial.readthedocs.io/ · BSD. Windows의 HC-06 Bluetooth COM 통신에 사용합니다.
- Arduino SoftwareSerial·Servo와 AVR 코어는 Arduino 공식 배포 라이선스를 따릅니다. 펌웨어는 사진의 핀 배선에 맞춰 직접 작성했습니다.
- Chaquopy 17.2.0: https://chaquo.com/chaquopy/ · MIT. Android Python 및 생성된 연결 코드를 제공합니다. Python 3.13 런타임은 PSF 라이선스를 따릅니다.
- Ultralytics YOLOv8: https://github.com/ultralytics/ultralytics · AGPL-3.0. 학습과 ONNX 내보내기에 사용합니다. `docs/licenses/ultralytics-AGPL-3.0.txt`에 전문을 보관합니다.
- BePLi v2: https://doi.org/10.17882/96963 · CC BY-NC-SA 4.0. 현재 학습 사진과 라벨의 출처입니다. `models/ATTRIBUTION.txt`에 저자·변경 사항을 기록합니다. 원본 사진은 APK에 넣지 않습니다.
- NumPy, OpenCV, PyTorch, ONNX, Pillow, Requests, Beautiful Soup는 각 배포 패키지의 라이선스를 따릅니다.

FLOW 영상 패킷은 공개 형식 자료를 참조해 Python으로 구현했습니다. OpenIPC 프로그램 소스는 포함하지 않습니다.

- https://github.com/marshallrichards/turbodrone/blob/main/docs/research/wifi_uav.md
- https://github.com/OpenIPC/decoder/blob/v2/docs/toys.md

이전 Kivy·Flask·폰트·Firmata·Grounding DINO 실험 소스와 출처 설명은 Git의 `android-v0.2.0` 태그에 보존되어 있습니다. 과거 검색 후보의 출처 기록은 현재 `data/`에도 유지합니다. 전체 배포물에 하나의 라이선스가 일괄 적용된다고 가정하지 마세요.
