# 외부 구성요소

- Ultralytics YOLOv8n: https://github.com/ultralytics/ultralytics (AGPL-3.0). `models/yolov8n.pt`는 학습 시작용 일반 COCO 가중치입니다. 그물 학습 결과는 `phone/models/model.json`과 모델 카드를 확인하세요. 이전 `prototype-20261124` Release의 ONNX는 일반 COCO 데모입니다. 라이선스 전문은 `docs/licenses/ultralytics-AGPL-3.0.txt`입니다.
- Noto Sans KR: https://github.com/notofonts/noto-cjk (SIL Open Font License 1.1). 폰트는 변경하지 않았습니다. 전문과 저작권 정보는 `phone/fonts/LICENSE.txt`입니다.
- Grounding DINO Tiny: https://huggingface.co/IDEA-Research/grounding-dino-tiny (Apache-2.0). 과거 사진 박스 제안 실험용이며 현재 학습에는 사용하지 않습니다. 가중치는 APK에 포함하지 않습니다.
- Chaquopy: https://chaquo.com/chaquopy/ (MIT). Android APK 안의 Python 런타임과 연결 코드에 사용합니다.
- ONNX Runtime: https://github.com/microsoft/onnxruntime (MIT). Android 추론 대상 엔진.
- pyFirmata2: https://github.com/berndporr/pyFirmata2 (LGPL-2.1), StandardFirmata: https://github.com/firmata/arduino . Arduino용 외부 펌웨어입니다.
- Flask, OpenCV, NumPy, Kivy, Pillow, Requests, Transformers는 각 배포 패키지의 라이선스를 따릅니다.
- 현재 학습 사진·라벨은 BePLi v2 공식 배포본(CC BY-NC-SA 4.0)에서 선별합니다: https://doi.org/10.17882/96963 . 출처와 변경 내용은 `phone/models/ATTRIBUTION.txt`, 사진별 ID·해시·박스는 `data/bepli_manifest.json`입니다. 원본 사진은 APK에 넣지 않습니다.
- 과거 Openverse/Flickr 및 Wikimedia Commons 검색 후보는 품질 문제로 학습에서 제외했습니다. 해당 보관본의 사진별 권리 정보는 `data/CANDIDATE_SOURCES.csv`와 `data/candidates.json`에 남깁니다.

이 저장소는 개발 중인 공개 저장소입니다. 전체 배포물에 하나의 라이선스가 일괄 적용된다고 가정하지 마세요.

웹 화면에는 ONNX Runtime Web 1.20.1의 WASM 런타임을 포함합니다. MIT 라이선스는 `web/vendor/LICENSE.txt`입니다. https://onnxruntime.ai/docs/tutorials/web/

APK: Chaquopy 17.2.0 (MIT)와 Python 3.13 런타임(PSF)을 사용합니다. FLOW 프로토콜은 공개 패킷 형식 자료를 참조해 Python으로 구현했습니다. OpenIPC 소스 코드는 포함하지 않았습니다.
