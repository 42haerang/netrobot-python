# NetRobot Python

그물 감지와 바퀴 로봇 조종을 위한 **개발 중인 프로젝트**입니다. 노트북 웹캠을 휴대폰에 전송하고, Android 기기에서 YOLO 추론을 실행하는 구조를 목표로 합니다. 먼저 GitHub에 소스와 수집 자료를 정리한 단계입니다.

## 현재 상태

- **구현·소프트웨어 검증:** 노트북 JPEG 전송, 토큰 인증, 전후좌우 모의 조종, 명령이 0.35초 끊기면 바퀴 정지, 데스크톱 ONNX 추론.
- **Android Python 소스:** 가로 카메라 배경, 감지 사각형·신뢰도, 왼쪽 방향키, 오른쪽 DC 집게 열기/닫기 버튼. Chaquopy 및 ONNX Runtime Android 연동을 작성했으나 **APK 빌드와 실제 Android 동작 검증은 아직 하지 않았습니다.** Android Gradle 프로젝트도 아직 없습니다.
- **집게:** 화면 버튼 소스만 있습니다. 서버 `/gripper` API와 다섯 번째 DC 모터 배선·제어는 아직 구현되지 않았습니다. 현재 실물 모터 연결용 완성본이 아닙니다.
- **사진:** 수집 후보 1,710장(그물 검색 1,085 / 비슷한 물체 366 / 기타 259). 검색 결과에는 오분류·중복이 있을 수 있습니다. 검수·박스 라벨링 후 **500 / 300 / 200장**, 학습 800 / 테스트 200으로 확정할 예정입니다. 이 수치는 아직 달성된 학습 데이터 수가 아닙니다.
- **모델:** 포함된 데모 ONNX는 일반 COCO YOLOv8n입니다. **그물 전용 학습은 아직 하지 않았습니다.** 자동 박스 제안은 정답 라벨이 아닙니다.

표시되는 `%`는 감지 신뢰도입니다. 실제 적합률(precision)은 검수된 테스트 데이터에서 별도로 평가해야 합니다.

## 구조

```text
노트북 웹캠 → Flask JPEG 서버 → Android 휴대폰의 YOLO 추론·화면
휴대폰 방향키 → Flask → USB Arduino Uno/Nano → 모터 드라이버 → 바퀴 4개
휴대폰 집게 버튼 → [서버·배선 구현 예정] → DC 집게 모터
```

현재 Arduino 연결은 노트북 USB를 경유합니다. 휴대폰과 Arduino의 직접 무선 연결은 구현되어 있지 않습니다. 직접 작성한 앱 로직은 Python이며, Android 런타임·추론 엔진·Firmata는 외부 라이브러리/펌웨어를 사용합니다.

| 경로 | 내용 |
|---|---|
| `pc/server.py` | 노트북 카메라·인증·바퀴 조종 API |
| `pc/motors.py` | 바퀴 4개 모의 조종/StandardFirmata 연동 |
| `phone/android_main.py` | 목표 Android 게임 화면 UI 소스, 미빌드 |
| `phone/onnx_android.py` | Android ONNX Runtime 추론 어댑터, 미검증 |
| `phone/main.py`, `detector.py` | 이전 세로형 데스크톱 미리보기·OpenCV 추론 검증용 |
| `tools/` | 사진 수집, 검토용 접촉 시트, 박스 제안, 분할·학습·변환 |
| `data/` | 출처·라이선스·후보 및 자동 제안 메타데이터 |
| `tests/` | 실제 모터를 구동하지 않는 소프트웨어 검사 |

## 노트북에서 실행

Python 3.13을 기준으로 개발했습니다. 프로젝트 폴더에서 실행합니다.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-pc.txt
.venv\Scripts\python tools/setup_local.py
.venv\Scripts\python pc/server.py
```

`setup_local.py`가 로컬 전용 토큰과 설정을 만듭니다. 이미 있는 파일은 덮어쓰지 않습니다. 기본값은 모의 조종입니다. `settings.json`과 `phone/config.json`은 Git에 포함하지 않습니다.

같은 Wi-Fi의 다른 기기는 `http://노트북IP:8765/health`로 연결 상태를 확인할 수 있습니다. 서버의 `/phone.zip`은 페어링 코드로 보호된 **Python 소스 묶음**이며 APK가 아닙니다. 서버는 로컬 네트워크용 프로토타입입니다.

### 데스크톱 미리보기

GitHub **Releases**의 `NetRobot_assets.zip`을 프로젝트 루트에 풀면 후보 사진·일반 데모 모델·한국어 폰트가 각각 원래 폴더에 들어갑니다. 개인 토큰은 들어 있지 않습니다.

```powershell
.venv\Scripts\python -m pip install -r requirements-preview.txt
.venv\Scripts\python phone/main.py
```

이 미리보기는 목표 가로형 Android 화면과 다르며, 여기서 실행한 추론은 PC 추론입니다. 휴대폰 성능을 측정한 결과로 해석하면 안 됩니다.

## 데이터와 학습

[데이터 설명](docs/DATASET.md)과 [외부 구성요소](docs/THIRD_PARTY.md)를 확인하세요. 원본 사진·모델·폰트는 저장소 용량을 줄이기 위해 Release 자산으로 분리합니다. 출처와 라이선스는 `data/CANDIDATE_SOURCES.csv`에 있습니다.

```powershell
.venv\Scripts\python -m pip install -r requirements-training.txt
.venv\Scripts\python tools/contact_sheet.py net 0
# 사람이 검수하고 data/review.json을 작성한 다음에만:
.venv\Scripts\python tools/prepare_dataset.py
.venv\Scripts\python tools/train.py --epochs 20
```

현재 `review.json`은 없습니다. 검수 없이 학습 준비가 끝났다고 표시하지 않도록 분할 도구가 중단됩니다. 자동 제안 도구는 `tools/suggest_boxes.py`이며 대형 Grounding DINO 모델을 별도 다운로드합니다. 테스트 200장은 학습·모델 선택에 사용하지 않습니다.

## 검사

```powershell
.venv\Scripts\python -m unittest discover -s tests -v
```

모델 파일이 없으면 ONNX 검사는 건너뜁니다. GitHub Actions는 모의 조종·인증·영상 API를 검사합니다. Android APK, 실제 배선, 집게 동작은 이 검사 범위에 포함되지 않습니다.

## 하드웨어 연결 전 남은 작업

모터 드라이버 모델과 모터 정격 전류를 정한 뒤 4개 바퀴와 집게 1개에 필요한 H-브리지 채널 및 핀 배치를 확정해야 합니다. 현재 설정은 바퀴 4개용 예시이며 집게 핀은 없습니다. Uno/Nano에는 StandardFirmata가 필요합니다. 전원은 모터 드라이버 사양에 맞춰 따로 공급해야 합니다.

현재 워치독은 노트북 프로세스가 살아 있을 때만 작동합니다. 프로세스 강제 종료나 PC 전원 상실에도 정지하는 하드웨어/펌웨어 대책을 추가하기 전에는 실물 구동용 완성본으로 사용할 수 없습니다.
