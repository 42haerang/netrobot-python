# 외부 구성요소

- Ultralytics YOLOv8n: https://github.com/ultralytics/ultralytics (AGPL-3.0). Release의 `models/yolov8n.pt`, `phone/models/net.onnx`는 이 모델의 원본/ONNX 변환 데모이며 그물 전용 모델이 아닙니다. 라이선스 전문은 `docs/licenses/ultralytics-AGPL-3.0.txt`입니다.
- Noto Sans KR: https://github.com/notofonts/noto-cjk (SIL Open Font License 1.1). 폰트는 변경하지 않았습니다. 전문과 저작권 정보는 `phone/fonts/LICENSE.txt`입니다.
- Grounding DINO Tiny: https://huggingface.co/IDEA-Research/grounding-dino-tiny (Apache-2.0). 사진 박스 제안용, 모델 가중치는 포함하지 않습니다.
- Chaquopy: https://chaquo.com/chaquopy/ (MIT). Android Python 연결 소스의 대상 런타임이며 아직 빌드되지 않았습니다.
- ONNX Runtime: https://github.com/microsoft/onnxruntime (MIT). Android 추론 대상 엔진.
- pyFirmata2: https://github.com/berndporr/pyFirmata2 (LGPL-2.1), StandardFirmata: https://github.com/firmata/arduino . Arduino용 외부 펌웨어입니다.
- Flask, OpenCV, NumPy, Kivy, Pillow, Requests, Transformers는 각 배포 패키지의 라이선스를 따릅니다.
- 사진은 Openverse/Flickr 및 Wikimedia Commons에서 수집했습니다. 사진별 권리 정보는 `data/CANDIDATE_SOURCES.csv`와 `data/candidates.json`을 확인하세요. BY-SA 사진은 해당 조건을 유지해야 합니다.

이 저장소는 개발 중인 공개 저장소입니다. 전체 배포물에 하나의 라이선스가 일괄 적용된다고 가정하지 마세요.

웹 화면에는 ONNX Runtime Web 1.20.1의 WASM 런타임을 포함합니다. MIT 라이선스는 `web/vendor/LICENSE.txt`입니다. https://onnxruntime.ai/docs/tutorials/web/

APK: Chaquopy 17.2.0 (MIT)와 Python 3.13 런타임(PSF)을 사용합니다. FLOW 프로토콜은 공개 패킷 형식 자료를 참조해 Python으로 구현했습니다. OpenIPC 소스 코드는 포함하지 않았습니다.
