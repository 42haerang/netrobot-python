# NETROBOT Drone · 인터넷 없이 쓰는 Android APK

**[그물 감지 시험용 APK v0.2.0 다운로드](https://github.com/42haerang/netrobot-python/releases/download/android-v0.2.0/NetRobot-Drone-v0.2.0.apk)** · [웹 조종 연습 화면](https://42haerang.github.io/netrobot-python/)

드론 Wi-Fi `FLOW_27AF9C`와 **WiFi UAV** 앱을 쓰는 FLOW 계열 카메라를 대상으로 한 실험용 APK입니다. Python(Chaquopy)으로 UDP 영상을 직접 받고, 앱에 포함된 웹 화면을 오프라인으로 표시합니다. 노트북 서버 주소·연결 코드를 입력할 필요가 없습니다.

## 사용

1. 인터넷이 되는 상태에서 APK를 휴대폰에 내려받아 설치합니다. 64비트 Android 7.0 이상이 대상입니다.
2. 기존 **WiFi UAV 앱을 종료**합니다. 드론이 한 클라이언트에만 영상을 줄 수 있습니다.
3. 휴대폰 Wi-Fi를 `FLOW_27AF9C`에 연결합니다. 인터넷이 없어도 해당 Wi-Fi 연결을 유지합니다.
4. **NetRobot Drone** 앱을 엽니다. 기본 주소 `192.168.169.1`에서 UDP 8800/8801을 확인합니다. 주소가 다른 기종은 설정에서 변경합니다.
5. 영상은 오는데 색이 이상하면 설정의 **영상 색상 방식**을 바꿔 봅니다.

화면·영상 수신·모의 조종·기어/집게 애니메이션·ONNX 추론 엔진은 APK 안에 들어 있습니다. 웹사이트 자체는 UDP를 직접 받을 수 없으므로 **실제 드론 영상은 APK에서** 연결합니다. 웹사이트는 조종 연습과 APK 다운로드용입니다.

**연결 확인:** 2026-11-24 사용자가 `FLOW_27AF9C`에 연결한 Android 휴대폰에서 드론 카메라 영상이 나온다고 확인했습니다(v0.1.0). 휴대폰/드론 모델명과 프레임 속도는 측정하지 않았습니다. 조종은 실물 로봇이 없어 모의 동작입니다. 드론에는 영상 요청과 영상 조각 ACK만 보내며, 비행/프로펠러 제어 명령은 보내지 않습니다.

**v0.2.0에는 BePLi v2 공식 사진·라벨로 학습한 그물 모델이 포함됩니다.** 설치 후 자동으로 불러와 드론 영상 위에 감지 박스와 신뢰도를 표시합니다. 추론은 휴대폰에서 오프라인으로 실행됩니다. 다른 1종류 `net` ONNX를 설정에서 선택해 기기에 저장할 수도 있습니다. v0.1.0에는 모델이 없었습니다.

그물 모델은 아직 성능이 낮습니다. 새로운 테스트 200장에서 정밀도 12.11%, 재현율 13.46%, mAP50 4.06%로 오탐과 누락이 많습니다. 실제 드론 시야에서의 성능은 추가 확인이 필요합니다. 박스 옆 %는 개별 감지의 신뢰도입니다. 학습 구성·측정한 성능·제한은 [모델 카드](phone/models/MODEL_CARD.md)와 `models/bepli_focus_test_metrics.json`에 기록합니다. 조종 버튼과 로봇 애니메이션은 실물 미연결 모의 동작입니다.

설정의 **그물 감지 켜기**로 추론과 박스 표시를 끌 수 있습니다. 영상과 조종 화면은 계속 표시합니다. 이 선택은 기기에 저장됩니다.

## 개발

- `android/app/src/main/python/drone_android.py`: Python Android Activity, 앱 내부 자원 제공, Wi-Fi 네트워크 연결.
- `android/app/src/main/python/flow_video.py`: FLOW UDP 조각 복원과 영상 ACK. 비행 제어는 없음.
- `web/`: 카메라 화면, 조이스틱, 모터 5개·기어·집게 모형, 표시 끄기, 브라우저 ONNX 추론.
- `tools/prepare_android.py`: 런타임 파일을 APK에 넣음. 실제 그물 모델만 포함하도록 검사함.
- `pc/`, `phone/`: 이전 노트북/Android 실험 소스. 현재 APK는 노트북 서버를 사용하지 않음.

빌드는 Python 3.13, JDK 21, Android SDK 36을 기준으로 했습니다. Android Studio의 SDK 경로를 `android/local.properties` 또는 `ANDROID_HOME`으로 지정하세요. 소스에는 직접 작성한 Java/Kotlin 코드는 없으며 Java 연결 코드는 Chaquopy가 생성합니다. 화면은 HTML/CSS/JavaScript입니다.

Git 소스에는 대용량 모델 파일을 넣지 않습니다. 모델을 포함해 다시 빌드하려면 Release의 `NetRobot-BePLi-focus-v2.onnx`를 `phone/models/net.onnx`로 저장하세요. 함께 제공하는 `model.json`의 SHA256과 대조한 뒤 APK에 넣습니다. 직접 학습하면 아래 학습 도구가 해당 파일과 메타데이터를 생성합니다.

```powershell
python tools/prepare_android.py
cd android
.\gradlew.bat assembleDebug
```

생성 파일: `android/app/build/outputs/apk/debug/app-debug.apk`. 디버그 키는 저장소에 올리지 않습니다.

```powershell
python -m unittest discover -s tests -v
node --test tests/web.test.mjs
```

화면은 카메라 배경·기본 버튼·단순한 조이스틱으로 구성합니다. 로봇 모형과 모터 색상/집게 애니메이션을 표시하고 끌 수 있습니다.

소프트웨어 검사에는 프레임 순서 뒤바뀜·중복 UDP 조각·JPEG 복원 결과·잘못된 길이·주소 및 모터 조종 검사가 포함됩니다. 실제 드론/로봇 실험을 대신하는 검사는 아닙니다.

`tools/check_export.py <best.pt> <검증사진> <작업폴더>`는 같은 입력에 대한 PyTorch와 APK 내 WASM 엔진의 출력을 비교합니다. 이 검사는 모델 변환과 추론 엔진의 일치를 확인하며 Android 기기에서의 실행 속도를 측정하는 검사는 아닙니다.

## 데이터

직접 촬영분 없이 공개 라벨 데이터셋으로 구성합니다. 기존 `data/raw/`, `candidates.json`, `box_suggestions.json`은 그물이 아닌 사진이 섞인 검색 후보이므로 학습에 쓰지 않습니다. `data/DATA_POLICY.json`을 확인하세요.

BePLi v2 공식 배포본: https://doi.org/10.17882/96963 (CC BY-NC-SA 4.0). 약 9.5GB의 원본 다운로드·압축 해제와 SHA256 기록을 완료했습니다. 바탕화면 프로젝트의 `data/labeled_sources/BePLi_v2/source/`에 원본·출처·체크섬을 보관합니다. 원본 해시: `5d27c9b103710223f928346f096a68d3f53211b1a30ce34d7815c8049458d711`.

활성 데이터 `data/dataset_bepli_focus/`에는 공식 `fishing_net` 박스를 변환한 1,000장과 YOLO 라벨이 있습니다. 그물 500장, 그물 없이 `rope`/`other_string`이 있는 300장, 나머지 200장입니다. 원본의 학습/검증/테스트 경계를 유지하여 학습 700장 + 검증 100장 = 개발용 800장, 최종 테스트 200장으로 구성합니다. 음성 사진은 라벨 파일을 비웁니다. SHA256·dHash로 선택 사진의 중복을 확인하고, 학습 사진의 전체 화면과 확대 영역을 표본 확인했습니다. 학습에만 실제 사진의 객체 영역 확대를 적용하고 검증·테스트는 원본 전체 화면을 유지합니다. 전체 사진을 사람이 재라벨링한 데이터라고 주장하지 않습니다.

```powershell
python tools/extract_bepli.py <106157.tar.gz> <extracted>
python tools/prepare_bepli.py <extracted/BePLi_dataset_v2/plastic_coco> <dataset_bepli>
python tools/train_bepli.py <dataset_bepli> --epochs 20 --threads 4
python tools/prepare_bepli_focus.py <plastic_coco> <dataset_bepli/manifest.json> <dataset_bepli_focus>
python tools/train_bepli_focus.py <dataset_bepli_focus> <baseline-last.pt> --epochs 8
```

YOLOv8n의 사전학습 가중치에서 시작해 원본 사진으로 20회 학습한 뒤, 객체 영역을 확대한 실제 학습 사진으로 8회 추가 학습했습니다. 두 단계에서 본 고유 학습 원본은 총 1,022장입니다. 현재 단계의 구성은 학습 700장·검증 100장·테스트 200장입니다. 원본 학습 모델은 초기 테스트에서 실패하여 배포에서 제외했으며, 그때 사용한 테스트 200장은 새 평가에서 제외했습니다. 이 이력과 제외 ID는 데이터 보고서에 보관합니다.

추가 학습은 입력 320×320, AdamW(lr=0.0003), 배치 16으로 수행했습니다. 최종 후보 두 개를 검증 100장에서 640 입력으로 비교한 뒤 새 테스트 200장을 한 번 평가했습니다. APK 입력은 640×640이며 추론은 가능한 환경에서 별도 Web Worker로 실행합니다. 원천 사진에는 생성 이미지와 이전 검색 후보가 들어가지 않습니다.

Littora 등 Roboflow 데이터는 다운로드 인증이 필요하며 아직 받지 못했습니다. 내려받은 것으로 표시하지 않습니다. 사진과 모델 배포 시 각 라이선스·출처를 유지해야 합니다.

## 프로토콜 출처 및 외부 구성요소

- WiFi UAV/FLOW 패킷 정보: https://github.com/marshallrichards/turbodrone/blob/main/docs/research/wifi_uav.md
- FLOW 영상 수신 호환성 참고: https://github.com/OpenIPC/decoder/blob/v2/docs/toys.md
- Chaquopy MIT, Python PSF, ONNX Runtime Web MIT. [외부 구성요소](docs/THIRD_PARTY.md).

