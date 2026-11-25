# NetRobot

노트북의 FLOW 드론 영상을 표시하고, Python OpenCV로 그물을 감지하며, Arduino USB/HC-06으로 앞바퀴 두 개와 SG90 집게를 조종합니다.

## 실행

```powershell
python -m pip install -r requirements.txt
python main.py --open
```

주소: http://127.0.0.1:8770/?bridge=1 . 바탕화면의 **드론 조종 시작** 바로가기도 같은 명령을 실행합니다. 드론 Wi-Fi에 인터넷이 없어도 로컬 화면과 추론은 실행됩니다. WiFi UAV 앱은 종료하세요. GitHub Pages는 화면 배포용이며, 실제 영상·모터·추론에는 로컬 Python 실행이 필요합니다.

## 파일

| 파일·폴더 | 역할 |
| --- | --- |
| `main.py` | 사이트와 카메라·모터 API 실행 |
| `camera.py`, `jpeg_headers.json` | FLOW UDP 영상 복원·재접속 |
| `motors.py` | Arduino USB/HC-06 통신과 정지 처리 |
| `yolo.py` | OpenCV DNN 추론·박스·신뢰도 표시 |
| `train.py`, `dataset.py` | YOLO 학습·내보내기, 공식 데이터 준비 |
| `web/` | HTML/CSS와 화면 Python, Brython 라이브러리 |
| `arduino/arduino.ino` | 아두이노 업로드 코드 |
| `models/` | ONNX 모델·학습 가중치·설명·출처·라이선스 |
| `dataset/` | 현재 학습 데이터와 라벨·분리 정보 |
| `tests/` | 실제 영상·모터·YOLO 기능 검사 |

사진·라벨과 학습 체크포인트는 바탕화면 실행본에 보관합니다. GitHub에는 큰 학습 사진을 올리지 않습니다. `jpeg_headers.json`은 드론 영상 복원, `models/model.json`은 모델 검사, `dataset`의 텍스트 라벨은 YOLO 학습에 필요합니다.

## 조종과 배선

설정에서 **Arduino USB (COM11)** 또는 HC-06 출력 COM을 선택하고 **아두이노 연결**을 누릅니다. 응답 확인 후 **모터 활성화**를 눌러 조종합니다. USB는 115200 baud, HC-06 COM은 9600 baud입니다. 현재 실물에서 확인한 경로는 USB이며, HC-06은 연결 시간 초과가 있어 무선 제어 성공으로 확인되지 않았습니다.

| 부품 | UNO 핀 |
| --- | --- |
| L298N ENA / IN1 / IN2 · 왼쪽 앞바퀴 | D5 / D7 / D8 |
| L298N ENB / IN3 / IN4 · 오른쪽 앞바퀴 | D6 / D12 / D13 |
| HC-06 TXD | D2 |
| HC-06 RXD | D4 → 1kΩ/2kΩ 분압 |
| SG90 신호 | D10 |
| GND | 공통 연결 |

ENA/ENB의 항상 켜짐 점퍼는 빼고 D5/D6을 연결합니다. 모터·서보에는 각 부품에 맞는 별도 전원을 공급합니다. 바퀴 방향이 반대라면 스케치의 `LEFT_SIGN` 또는 `RIGHT_SIGN`을 -1로 바꿉니다.

주행 PWM은 -255~255, 기본 최대 출력은 100%입니다. 집게는 0~180도 명령을 10ms마다 6도씩 갱신하며 실제 속도·도달 각도는 서보와 기구에 따릅니다. 조이스틱·집게 버튼을 놓으면 추가 이동 명령이 멈춥니다. 긴급 정지·화면 이탈은 비활성화하고, Python 0.4초·Arduino 0.6초 동안 조종 신호가 없으면 정지합니다. 자동으로 다시 활성화하지 않습니다.

## YOLO

현재 BePLi v2의 실제 사진과 발행자 수작업 fishing_net 라벨을 사용한 시험용 YOLOv8n 모델입니다. 1,000장: 학습 700·검증 100·테스트 200. 테스트 정밀도 12.11%, 재현율 13.46%, mAP50 4.06%로 오탐과 누락이 많습니다. 박스의 %는 개별 감지 점수입니다. 자세한 출처와 평가 정보는 `models/`와 `dataset/report.json`에 있습니다.

```powershell
python -m pip install -r requirements-training.txt
python train.py train dataset models/net_bepli_focus_v2.pt --epochs 8
python train.py export models/net_bepli_focus_v2.pt
```

데이터 재다운로드가 필요하면 `python dataset.py --help`를 확인하세요. 원본을 새로 받는 경우에만 다운로드·압축 해제를 실행합니다.

## 검사

```powershell
python -m unittest discover -s tests -v
```

모터 자동 검사는 가상 포트를 사용합니다. 실물 회전·집게 이동 성능 측정과 구분합니다.

## 외부 구성요소

- Brython 3.15.0: BSD-3-Clause. `web/vendor/BRYTHON-LICENSE.txt`.
- OpenCV: Apache-2.0. pySerial: BSD. 나머지 Python 패키지는 각 배포 라이선스를 따릅니다.
- Ultralytics YOLO: AGPL-3.0. `models/ULTRALYTICS-LICENSE.txt`.
- BePLi v2: CC BY-NC-SA 4.0. https://doi.org/10.17882/96963 . 저자와 변경 사항은 `models/ATTRIBUTION.txt`.
- Arduino Servo·SoftwareSerial·AVR 코어는 공식 배포 라이선스를 따릅니다.
- FLOW 패킷 형식 참고: https://github.com/marshallrichards/turbodrone/blob/main/docs/research/wifi_uav.md , https://github.com/OpenIPC/decoder/blob/v2/docs/toys.md . OpenIPC 프로그램 코드를 포함하지 않습니다.
