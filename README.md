# NetRobot · Python OpenCV와 실제 앞바퀴 제어

[GitHub 소스](https://github.com/42haerang/netrobot-python) · [배포 화면](https://42haerang.github.io/netrobot-python/)

실제 조종과 감지는 노트북의 **로컬 사이트**에서 실행합니다. 인터넷이 없는 드론 Wi-Fi에서도 동작하도록 화면·모델·라이브러리를 노트북에 저장합니다. GitHub Pages는 소스와 화면 배포용이며 Python이나 HC-06을 직접 실행하지 않습니다.

```powershell
python -m pip install -r requirements.txt
python tools/build.py control --open
```

조종 주소: **http://127.0.0.1:8770/?bridge=1**. 준비된 노트북에서는 바탕화면 **드론 조종 시작** 바로가기를 사용합니다. 드론 Wi-Fi에 연결하면 영상 수신을 자동으로 재시도합니다. 기존 WiFi UAV 앱은 종료하세요. 드론 영상에 노트북 웹캠을 쓰지 않습니다.

## 실제 모터 연결

**현재 USB 연결이 확인됐습니다.** USB 케이블을 꽂아 둔 상태로 설정에서 `Arduino USB (COM11)` → **아두이노 연결**을 선택합니다. 화면에 **USB 연결됨 · 비활성**이 뜨면 모터 활성화로 조종할 수 있습니다. 실제 COM11에서 펌웨어 인사와 정지 응답을 확인했으며 바퀴 회전·집게 이동은 아직 시험하지 않았습니다. HC-06 무선은 별도로 연결 문제를 조사 중입니다.


구성은 Arduino UNO/Nano(ATmega328P), L298N, HC-06, 좌우 앞바퀴 DC 모터 2개, SG90 집게입니다. 뒷바퀴 모터와 로봇 그림은 제거했습니다. 조종이 모의 동작인 것처럼 표시하지 않으며, 연결·활성화 전에는 조종 입력을 받지 않습니다.

1. Arduino IDE에서 `firmware/netrobot_front/netrobot_front.ino`를 업로드합니다. UNO 컴파일과 USB 업로드 검증을 수행했습니다.
2. Windows에서 HC-06을 페어링합니다. HC-06은 Classic Bluetooth SPP이므로 BLE용 Web Bluetooth 대신 Python과 Windows COM 포트를 사용합니다.
3. 로컬 사이트의 설정에서 **포트 새로고침 → HC-06 출력 COM → 아두이노 연결**을 선택합니다. 현재 노트북에서 확인한 HC-06 포트는 COM13입니다. 다른 기기에서는 바뀔 수 있습니다.
4. 펌웨어의 `NETROBOT 1` 응답이 확인된 뒤에만 연결됨으로 표시합니다. Windows 페어링이나 COM 포트가 열리는 것만으로는 제어 연결 성공으로 처리하지 않습니다.
5. 바퀴를 띄운 상태에서 **모터 활성화**를 눌러 방향을 확인합니다. 그다음 왼쪽 조이스틱으로 앞바퀴 두 개를, 오른쪽 열기·닫기로 SG90을 조작합니다.

### 배선

| 부품 | Arduino 핀 |
| --- | --- |
| L298N ENA / IN1 / IN2 · 왼쪽 앞바퀴 | D5 / D7 / D8 |
| L298N ENB / IN3 / IN4 · 오른쪽 앞바퀴 | D6 / D12 / D13 |
| HC-06 TXD | D2 (소프트웨어 RX) |
| HC-06 RXD | D4 (소프트웨어 TX)에서 1kΩ/2kΩ 분압 후 연결 |
| SG90 신호 | D10 |
| 신호 기준 GND | 공통 연결 |

ENA/ENB의 항상 켜짐 점퍼는 제거하고 D5/D6을 연결합니다. L298N의 모터 전원과 5V 논리 전원도 각각 정상 공급되어야 합니다. 별도 전원들의 +를 임의로 묶지 않습니다. 실제 모듈의 5V 전원/레귤레이터 점퍼는 해당 보드 설명을 따르세요.

한쪽 바퀴가 반대로 돌면 스케치의 `LEFT_SIGN` 또는 `RIGHT_SIGN`을 -1로 바꿉니다. SG90의 이전 70~110도 제한을 해제해 명령 범위 0~180도를 사용하고, 10ms마다 6도씩 명령을 갱신합니다. 이는 명령 속도이며 실제 회전 속도·도달 각도는 서보 제품과 집게 부하에 따라 다릅니다. 일반 위치 서보가 연속 회전형으로 바뀌는 것은 아닙니다. 실제 기구에 맞춰 `GRIP_CLOSED`, `GRIP_OPEN`을 조절합니다. USB와 HC-06은 같은 명령 형식을 사용하며 USB는 115200 baud, HC-06의 Windows COM은 9600 baud입니다. UNO 코드만 C++이고 노트북 기능과 화면 동작은 Python입니다.

### 정지 동작

연결만으로는 모터를 켜지 않습니다. 조이스틱을 놓으면 두 바퀴 명령이 0이 되고 집게 버튼을 놓으면 현재 각도를 유지합니다. 긴급 정지·화면 이탈은 비활성화하며 복귀만으로 다시 움직이지 않습니다. 브라우저 입력이 0.4초 끊기면 Python에서 정지하고, Arduino도 유효 명령이 0.6초 없으면 정지합니다. 다시 활성화해야 재출발합니다. 표시되는 %는 명령 출력이며 측정한 바퀴 RPM이 아닙니다.

스케치는 HC-06의 일반적인 UART 속도를 순서대로 확인하고 `HELLO`를 받은 속도로 고정합니다. USB 진단은 115200 baud이며 부팅 시 `NETROBOT READY - MOTORS DISARMED`, Bluetooth 인사 수신 시 `HC06 LINK <속도>`를 출력합니다. 인사 응답 전에 ARM 명령을 받아도 움직이지 않습니다.

## OpenCV 처리

실시간 추론은 **OpenCV 4.12의 `cv2.dnn.readNetFromONNX`, `blobFromImage`, `forward`, `NMSBoxes`**로 실행합니다. `imdecode`로 JPEG를 읽고, 640×640 회색 여백·RGB·0~1 입력으로 변환합니다. 출력 `[1,5,8400]`에서 후보를 고르고, 원본 좌표로 되돌린 뒤 NMS IoU 0.45로 중복을 줄입니다. 박스와 %는 `cv2.rectangle`, `cv2.putText`로 그려 JPEG로 반환합니다. 사이트는 완성된 영상을 표시합니다. ONNX는 모델 형식이며 ONNX Runtime Web을 실행하는 것이 아닙니다.

설정에서 사진·영상 파일이나 접근을 허용한 JPEG 카메라 주소를 선택해도 같은 OpenCV 처리를 거칩니다. 파일 프레임은 현재 노트북의 로컬 서버로 전송하며 인터넷으로 보내지 않습니다. RTSP/MJPEG 주소를 그대로 입력하는 기능은 아닙니다. CORS/HTTPS를 허용하는 카메라 주소가 필요합니다.

모델은 `models/net.onnx`와 `models/model.json`입니다. 이전 BePLi focus v2 가중치를 그대로 사용했습니다. 테스트 정밀도 12.11%, 재현율 13.46%, mAP50 4.06%인 시험용 모델로 오탐과 누락이 많습니다. OpenCV 전환으로 정확도가 개선됐다고 주장하지 않습니다. [모델 카드](models/MODEL_CARD.md)와 [출처](models/ATTRIBUTION.txt)를 확인하세요.

## 코드 구성

| 파일 | 역할 |
| --- | --- |
| `web/index.html` | 기본 화면과 스타일, 조이스틱, 집게, 연결 설정 |
| `web/app.py` | 화면 입력, OpenCV 프레임 요청, 모터 명령 전송 |
| `tools/build.py` | 로컬 사이트와 영상·OpenCV·모터 HTTP API |
| `tools/vision.py` | OpenCV DNN 추론, NMS, 박스와 점수 표시 |
| `tools/motors.py` | HC-06 COM 연결, 펌웨어 응답 확인, 주기적 전송·정지 |
| `android/app/src/main/python/flow_video.py` | FLOW UDP 영상 복원·재접속. 비행 명령은 보내지 않음 |
| `firmware/netrobot_front/netrobot_front.ino` | 앞바퀴 2개·SG90·통신 감시 |
| `tools/data.py`, `tools/model.py` | 기존 공식 데이터 선별·학습·ONNX 내보내기 |

브라우저의 Python은 Brython으로 실행합니다. 직접 작성한 기능용 JavaScript와 브라우저 ONNX Runtime은 사용하지 않습니다. 과거 Android 앱 소스와 Release는 보존하지만 현재 OpenCV/모터 조종 경로는 로컬 Python 사이트입니다.

## 검사

```powershell
python -m unittest discover -s tests -v
```

OpenCV 실제 ONNX 추론과 JPEG 출력, 잘못된 입력, 모터 연결 시 비활성 유지, 잘못된 출력 거부, 브라우저 신호 중단 정지, HTTP 접근 제한과 UDP JPEG 복원을 검사합니다. 모터 검사는 가상 직렬 포트로 수행하며 실물 회전 검증과 구분합니다.

BePLi v2 공식 사진·수작업 fishing_net 라벨을 사용합니다. 현재 선별 1,000장은 그물 포함 500·비슷한 음성 300·기타 음성 200, 학습 700·검증 100·테스트 200입니다. 직접 촬영·생성된 그물·과거 검색 후보는 현재 학습에서 제외합니다. [데이터 이력](docs/DATASET.md), [기기 확인 기록](docs/DEVICE_CHECK.md), [외부 구성요소](docs/THIRD_PARTY.md)를 참고하세요.

주행 출력은 0~100% 전체 범위를 사용하며 기본 최대 출력은 100%입니다. Arduino PWM은 -255~255를 허용합니다. 조이스틱을 조금 움직이면 낮은 출력이, 끝까지 밀면 설정한 최대 출력이 전달됩니다. 통신 끊김 정지는 유지하고 서보 명령은 0~180도를 사용합니다.
