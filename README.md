# NetRobot · Python 중심 그물 감지와 조종 화면

[웹사이트](https://42haerang.github.io/netrobot-python/) · [APK v0.3.0 다운로드](https://github.com/42haerang/netrobot-python/releases/download/android-v0.3.0/NetRobot-Drone-v0.3.0.apk)

카메라를 배경으로 그물 박스와 신뢰도, 왼쪽 터치 조이스틱, 오른쪽 집게 열기·닫기를 표시합니다. 가운데 로봇은 바퀴 모터 4개와 집게 모터 1개·기어·집게를 보여 주며 숨길 수 있습니다. 디자인은 기본 버튼과 단순한 패널을 사용합니다.

## 코드 파일

직접 작성하는 주요 Python 파일은 **6개**로 묶었습니다. 각 기능 덩어리 앞에 한국어 주석을 넣고, 어려운 축약문과 한 줄에 여러 동작을 쓰는 코드를 풀었습니다.

| 파일 | 하는 일 |
| --- | --- |
| `web/app.py` | 화면 버튼, 조이스틱, 모터 애니메이션, 모델 저장, 영상 표시, YOLO 실행과 박스 표시 |
| `android/app/src/main/python/drone_android.py` | GitHub 화면 읽기, 오프라인 사본, Android 파일 선택·Wi-Fi 설정·영상 API |
| `android/app/src/main/python/flow_video.py` | 실제로 연결이 확인된 FLOW/WiFi UAV UDP 영상 수신·JPEG 복원 |
| `tools/data.py` | 공식 데이터 다운로드·압축 해제·중복 제거·사진 선별·YOLO 라벨 변환 |
| `tools/model.py` | 학습·평가·ONNX 내보내기·수치 검사 |
| `tools/build.py` | 웹 미리보기·APK 자원 준비·빌드·GitHub Release 업로드 |

화면 구조·스타일·로봇 SVG는 **`web/index.html` 하나**에 모았습니다. 검사는 `tests/test_app.py`, `tests/test_flow_video.py` 두 파일입니다. 예전 JS 화면, PC 서버, Kivy 실험, 여러 수집 스크립트는 현재 소스에서 정리했고 Git의 `android-v0.2.0` 태그에 남아 있습니다. 원본 사진과 학습 결과 파일은 삭제하지 않았습니다.

JPEG 헤더 100개도 내용이 같은지 확인한 뒤 `android/app/src/main/assets/jpeg_headers.json` 한 파일로 묶었습니다. `android/app/src/main/assets/web/`는 빌드할 때 만드는 사본이므로 Git에서는 제외하고 `web/` 원본만 관리합니다.

Python 코드도 브라우저에서 실행하도록 Brython을 사용합니다. `web/vendor/`의 Brython·ONNX Runtime JS/WASM은 외부 실행 라이브러리이며 직접 만든 기능 코드는 Python에 있습니다. 브라우저 시작용 Brython 호출, Android의 화면 숨김·복귀 콜백 호출, Gradle/XML 등 Android 설정은 해당 플랫폼의 연결 형식을 사용합니다. 브라우저가 Python이나 UDP를 기본 지원하는 것은 아닙니다.

## 설치와 사용

1. 인터넷이 될 때 APK를 다운로드해 설치합니다. 64비트 Android 7.0 이상이 대상입니다.
2. 원래 사용하던 **WiFi UAV** 앱을 종료합니다.
3. 휴대폰 Wi-Fi를 `FLOW_27AF9C`에 연결하고 인터넷이 없어도 연결을 유지합니다.
4. **NetRobot Drone**을 실행합니다. 기본 드론 주소는 `192.168.169.1`, 영상 포트는 UDP 8800·8801입니다.
5. 색상이 이상하면 설정에서 영상 색상 방식을 변경합니다.

APK는 `https://42haerang.github.io/netrobot-python/?app=1`을 엽니다. 인터넷이 있으면 GitHub의 HTML과 Python을 함께 읽고 버전·SHA256을 검사합니다. 인터넷이 없거나 다른 버전이면 **APK 안에 넣은 같은 화면**을 사용합니다. 모델과 외부 실행 라이브러리는 APK에서 읽으므로 드론 Wi-Fi에 인터넷이 없어도 사용할 수 있습니다. 설정에 화면 출처가 표시됩니다.

일반 Chrome에서 여는 GitHub 사이트는 조종 연습과 ONNX 모델 불러오기가 가능합니다. 웹 브라우저에는 드론의 UDP 패킷을 받는 기능이 없으므로 실제 드론 영상 수신에는 Python 수신부를 넣은 APK가 필요합니다. APK가 연 사이트에서는 이 수신부를 통해 영상을 표시합니다. 노트북 웹캠·노트북 서버·연결 코드는 사용하지 않습니다.

## YOLO 처리

Python 수신부가 JPEG 한 장을 복원하면 `app.py`가 새 영상만 캔버스에 표시합니다. 별도 반복 함수가 영상을 640×640 회색 여백 이미지로 바꾸고 RGB/NCHW/0~1 숫자로 변환해 ONNX Runtime에 전달합니다. 출력은 `[1, 5, 8400]`이며 4개 좌표와 그물 점수입니다. 점수가 기준 이상인 후보의 여백을 제거하고 원래 영상 좌표로 바꿉니다. 같은 물체의 겹친 박스는 IoU 0.45 기준으로 하나만 남기고 박스와 점수를 그립니다.

추론은 한 번에 한 장씩 실행하고 완료 후 0.1초를 쉽니다. 추론 시간이 추가되므로 고정 10 FPS를 보장하지 않습니다. 사진을 계속 저장하거나 사용 중에 자동 재학습하지 않습니다. 휴대폰에서 모델을 실행하며 클라우드 AI는 사용하지 않습니다. %는 개별 감지 신뢰도이고 전체 정확도가 아닙니다.

기본 모델은 기존 v0.2.0과 같은 **BePLi focus v2**입니다. 이번 변경에서 재학습하거나 성능을 높였다고 주장하지 않습니다. 테스트 200장에서 정밀도 **12.11%**, 재현율 **13.46%**, mAP50 **4.06%**로 오탐과 누락이 많습니다. [모델 카드](models/MODEL_CARD.md), [출처](models/ATTRIBUTION.txt), `models/bepli_focus_test_metrics.json`을 확인하세요. 실제 바퀴·집게 연결은 아직 없으며 버튼은 모의 조종입니다.

## 실행과 빌드

Python 3.13을 사용합니다. 필요한 작업에 맞게 의존성을 설치하세요.

```powershell
python -m pip install -r requirements.txt
python tools/build.py preview --port 8765
python -m unittest discover -s tests -v
```

빌드에는 JDK 21, Android SDK 36이 필요합니다. SDK 경로는 `android/local.properties` 또는 `ANDROID_HOME`으로 지정합니다. Git에 대용량 모델을 넣지 않으므로 Release에서 `NetRobot-BePLi-focus-v2.onnx`를 받아 **`models/net.onnx`**로 저장해야 합니다. `models/model.json`의 SHA256과 일치해야 빌드합니다.

```powershell
$env:JAVA_HOME = 'C:\Program Files\Android\Android Studio\jbr'
$env:NETROBOT_BUILD_PYTHON = (Get-Command python).Source
python tools/build.py apk
```

`build.py`가 화면 코드의 해시를 HTML에 기록하고 `web/`와 모델을 Android 자원 폴더에 복사합니다. Gradle이 Chaquopy의 Python 런타임과 생성된 Android 연결 코드를 묶습니다. 직접 작성한 Java/Kotlin 파일은 없습니다. 결과는 `NetRobot-Drone-v0.3.0.apk`와 `.apk.sha256`입니다. 디버그 서명 APK이며 키는 공개하지 않습니다.

## 데이터와 학습

직접 촬영 사진 대신 공식 BePLi v2 수작업 라벨을 사용합니다. 현재 데이터 1,000장은 그물 포함 500장·비슷하지만 그물 없는 300장·기타 200장입니다. 학습 700장+검증 100장=개발 800장, 테스트 200장으로 구분합니다. 음성 사진의 라벨은 빈 파일입니다. 자세한 이력은 [데이터 설명](docs/DATASET.md)을 보세요.

```powershell
python -m pip install -r requirements-training.txt
python tools/data.py download data/labeled_sources/BePLi_v2/source
python tools/data.py extract data/labeled_sources/BePLi_v2/source/106157.tar.gz data/labeled_sources/BePLi_v2/extracted
python tools/data.py prepare <plastic_coco폴더> data/bepli_baseline_manifest.json <새데이터폴더>
python tools/model.py train <새데이터폴더> <초기모델.pt> --epochs 8
python tools/model.py check <선택된모델.pt> <검증사진.png>
```

기존 데이터 폴더를 덮어쓰지 않습니다. 후보 모델은 검증 사진으로 선택하고 마지막에 별도 테스트를 평가합니다. 이미 확인한 테스트를 반복해 튜닝할 경우 새로운 평가 데이터가 필요합니다. ONNX 수치 검사는 탐지 정확도나 Android 속도 검증과 별개입니다.

## 확인 범위

Python 계산·주소 제한·UDP 조각 순서/중복·JPEG 복원 검사와 Chromium의 Python 화면·모델 초기 추론·저장/복원 검사를 수행했습니다. v0.1.0 영상 수신은 사용자가 실물 기기에서 확인했습니다. 새 v0.3.0 APK의 Android 실행과 그물 성능은 실물 확인이 필요합니다. [기기 확인 기록](docs/DEVICE_CHECK.md), [외부 구성요소](docs/THIRD_PARTY.md)를 참조하세요.
