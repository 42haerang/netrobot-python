# NetRobot · 사이트 안에서 사용하는 조종 화면

**[조종 사이트 열기](https://42haerang.github.io/netrobot-python/)**

사이트를 열면 곧바로 왼쪽 터치 조이스틱, 오른쪽 집게 열기·닫기, 가운데 바퀴 모터 4개·집게 모터 1개·기어·집게 모형이 보입니다. 설치 페이지를 거치지 않으며 사이트에서 다른 앱을 실행하지 않습니다. 로봇 모형 숨김과 긴급 정지 버튼도 같은 화면에서 동작합니다. 현재는 실물 모터가 없어 모의 조종입니다.

## 사이트 사용

기본 그물 모델이 자동으로 로드됩니다. 첫 접속에는 실행 라이브러리와 모델 약 30 MB를 받으므로 인터넷이 필요합니다. 설정의 **영상 입력**에서 다음을 선택합니다.

- **사진·영상 파일:** 기기의 파일을 사이트 안에서 열고 실제 모델로 그물 박스와 신뢰도를 표시합니다. 파일은 서버에 올리지 않습니다. 브라우저가 지원하는 영상 형식이어야 합니다.
- **JPEG 카메라 주소:** 접근을 허용한 JPEG 이미지 주소를 반복해서 가져옵니다. CORS 허용이 필요하며 HTTPS 페이지에서는 HTTPS 주소를 사용해야 합니다. RTSP나 MJPEG 스트림 주소를 그대로 넣는 기능은 아닙니다.
- **FLOW 드론 · Python 수신부:** 아래 Python 수신부가 제공하는 같은 조종 페이지에서 UDP 드론 영상을 연결합니다.

조이스틱은 누른 방향으로 가상 바퀴를 움직이고 놓으면 멈춥니다. 집게도 누르는 동안 움직입니다. **조종 연습**은 표시용 가상 그림으로 실제 감지와 구분합니다. 로봇 모형 표시를 끄면 영상과 조종 버튼이 남습니다.

## 실제 FLOW 드론 영상 · APK 없이 사용

일반 웹사이트에는 raw UDP 수신 기능이 없습니다. FLOW/WiFi UAV 카메라는 Python으로 UDP 8800·8801을 받아 JPEG로 변환해야 합니다. 이 제약은 브라우저의 통신 API 때문이며 Wi-Fi 이름만으로 해결되지 않습니다. [Chrome 공식 설명](https://developer.chrome.com/docs/iwa/direct-sockets)을 참조하세요.

드론 Wi-Fi에 연결한 Python 실행 기기에서 아래 명령을 실행하세요. 이 기기는 노트북이나 Python을 실행할 수 있는 다른 기기가 될 수 있습니다. 휴대폰 브라우저만으로 Python 수신부가 자동 실행되는 것은 아닙니다.

```powershell
python -m pip install requests
python tools/build.py control
```

출력된 `http://127.0.0.1:8765/?bridge=1`을 같은 기기의 브라우저에서 열면 **사이트 안에서** 영상·YOLO·조종을 사용합니다. 기본 드론 주소는 `192.168.169.1`이며 노트북 웹캠은 사용하지 않습니다. 기존 WiFi UAV 앱은 종료하세요.

수신 기기와 휴대폰이 같은 Wi-Fi에서 서로 통신할 수 있다면 다음처럼 실행하고, 휴대폰에서 수신 기기의 Wi-Fi IP 주소로 접속합니다.

```powershell
python tools/build.py control --bind 0.0.0.0
```

휴대폰 주소는 `http://<수신 기기의 Wi-Fi IP>:8765/?bridge=1`입니다. 드론 AP의 기기 간 통신 허용 여부와 방화벽 설정에 따라 연결이 달라질 수 있으며 해당 실물 구성을 확인하지는 못했습니다. 수신부가 모델·화면 파일까지 제공하므로 이 경로는 인터넷 없이 같은 네트워크에서 사용할 수 있습니다. GitHub 공개 사이트는 UDP 중계 서버가 아닙니다.

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

## 미리보기와 검사

```powershell
python -m pip install -r requirements.txt
python tools/build.py preview --port 8765
python -m unittest discover -s tests -v
```

Python 수신부는 조종 페이지와 JPEG API를 함께 제공합니다. 다른 사이트에서 오는 카메라 요청은 거부합니다. 모터 명령을 실물 Arduino로 전송하는 기능은 아직 없으며 가상 조종 상태에만 적용됩니다. 모터 드라이버와 배선이 정해진 뒤 실제 제어를 연결해야 합니다.

## 그물 모델

기존 BePLi focus v2 ONNX와 모델 설명·출처를 `web/models/`에 포함했습니다. YOLO 호출과 좌표 변환은 브라우저의 Python에서 수행하고 ONNX Runtime Web이 계산합니다. 입력 640×640, 출력 `[1, 5, 8400]`, 기본 점수 40%, NMS IoU 0.45입니다. 추론은 한 장씩 실행하고 완료 후 0.1초를 쉬며 고정 10 FPS를 보장하지 않습니다. 기기에서 재학습하지 않습니다.

가중치는 이번 변경에서 재학습하지 않았습니다. 테스트 정밀도 12.11%, 재현율 13.46%, mAP50 4.06%로 오탐과 누락이 많습니다. 박스의 %는 개별 감지 점수이며 전체 정확도가 아닙니다. [모델 카드](web/models/MODEL_CARD.md)와 [출처](web/models/ATTRIBUTION.txt)를 확인하세요.

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

## 확인 범위와 이전 앱

Chromium에서 기본 모델 자동 로드, 실제 검증 사진과 영상 파일의 감지, 집게 동작·해제와 로봇 숨김을 확인했습니다. HTTP 영상 API의 상태·JPEG 응답·잘못된 드론 IP·다른 사이트 요청 거부를 포함해 자동 검사 8개를 수행합니다. 새 웹 구성으로 실제 드론과 휴대폰을 함께 연결한 시험은 아직 하지 않았습니다.

기존 APK와 Android 소스는 이전 사용자용으로 보존합니다. 현재 공개 사이트의 화면 버전은 4이며 이전 APK는 자체 버전 3 사본을 유지합니다. 이번 변경은 새 APK를 설치하거나 실행하게 하지 않습니다. 이력은 [기기 확인 기록](docs/DEVICE_CHECK.md), 라이선스는 [외부 구성요소](docs/THIRD_PARTY.md)에 기록합니다.
