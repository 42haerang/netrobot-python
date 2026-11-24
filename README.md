# NETROBOT Drone · 인터넷 없이 쓰는 Android APK

**[Android APK 다운로드](https://github.com/42haerang/netrobot-python/releases/download/android-v0.1.0/NetRobot-Drone-v0.1.0.apk)** · [웹 조종 연습 화면](https://42haerang.github.io/netrobot-python/)

드론 Wi-Fi `FLOW_27AF9C`와 **WiFi UAV** 앱을 쓰는 FLOW 계열 카메라를 대상으로 한 첫 테스트 APK입니다. Python(Chaquopy)으로 UDP 영상을 직접 받고, 앱에 포함된 웹 화면을 오프라인으로 표시합니다. 노트북 서버 주소·연결 코드를 입력할 필요가 없습니다.

## 사용

1. 인터넷이 되는 상태에서 APK를 휴대폰에 내려받아 설치합니다. 64비트 Android 7.0 이상이 대상입니다.
2. 기존 **WiFi UAV 앱을 종료**합니다. 드론이 한 클라이언트에만 영상을 줄 수 있습니다.
3. 휴대폰 Wi-Fi를 `FLOW_27AF9C`에 연결합니다. 인터넷이 없어도 해당 Wi-Fi 연결을 유지합니다.
4. **NetRobot Drone** 앱을 엽니다. 기본 주소 `192.168.169.1`에서 UDP 8800/8801을 확인합니다. 주소가 다른 기종은 설정에서 변경합니다.
5. 영상은 오는데 색이 이상하면 설정의 **영상 색상 방식**을 바꿔 봅니다.

화면·영상 수신·모의 조종·기어/집게 애니메이션·ONNX 추론 엔진은 APK 안에 들어 있습니다. 웹사이트 자체는 UDP를 직접 받을 수 없으므로 **실제 드론 영상은 APK에서** 연결합니다. 웹사이트는 조종 연습과 APK 다운로드용입니다.

**현재 한계:** APK 빌드·서명과 JPEG 조각 복원 소프트웨어 검사를 완료했습니다. 실제 휴대폰과 해당 드론에서의 수신은 아직 검증하지 못했습니다. 조종은 실물 로봇이 없어 모의 동작입니다. 드론에는 영상 요청과 영상 조각 ACK만 보내며, 비행/프로펠러 제어 명령은 보내지 않습니다.

**그물 모델은 아직 미포함입니다.** 기존 검색 후보와 자동 박스 제안은 품질 문제로 학습에서 제외했습니다. 공식 라벨 데이터 다운로드·검수가 끝난 뒤 학습해야 합니다. 일반 COCO 모델이나 가짜 테스트 모델을 그물 모델로 바꿔 넣지 않습니다. 학습한 1종류 `net` ONNX를 설정에서 선택하면 기기에 저장하여 다음 실행에도 오프라인으로 불러옵니다. 추론은 휴대폰에서 실행됩니다.

## 개발

- `android/app/src/main/python/drone_android.py`: Python Android Activity, 앱 내부 자원 제공, Wi-Fi 네트워크 연결.
- `android/app/src/main/python/flow_video.py`: FLOW UDP 조각 복원과 영상 ACK. 비행 제어는 없음.
- `web/`: 카메라 화면, 조이스틱, 모터 5개·기어·집게 모형, 표시 끄기, 브라우저 ONNX 추론.
- `tools/prepare_android.py`: 런타임 파일을 APK에 넣음. 실제 그물 모델만 포함하도록 검사함.
- `pc/`, `phone/`: 이전 노트북/Android 실험 소스. 현재 APK는 노트북 서버를 사용하지 않음.

빌드는 Python 3.13, JDK 21, Android SDK 36을 기준으로 했습니다. Android Studio의 SDK 경로를 `android/local.properties` 또는 `ANDROID_HOME`으로 지정하세요. 소스에는 직접 작성한 Java/Kotlin 코드는 없으며 Java 연결 코드는 Chaquopy가 생성합니다. 화면은 HTML/CSS/JavaScript입니다.

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

소프트웨어 검사에는 프레임 순서 뒤바뀜·중복 UDP 조각·JPEG 복원 결과·잘못된 길이·주소 및 모터 조종 검사가 포함됩니다. 실제 드론/로봇 실험을 대신하는 검사는 아닙니다.

## 데이터

직접 촬영분 없이 공개 라벨 데이터셋으로 구성합니다. 기존 `data/raw/`, `candidates.json`, `box_suggestions.json`은 그물이 아닌 사진이 섞인 검색 후보이므로 학습에 쓰지 않습니다. `data/DATA_POLICY.json`을 확인하세요.

BePLi v2 공식 배포본: https://doi.org/10.17882/96963 (CC BY-NC-SA 4.0). 원본은 약 9.5GB이며 바탕화면 프로젝트의 `data/labeled_sources/BePLi_v2/source/`로 다운로드 중입니다. 완료 여부는 `SOURCE.json`의 `download_complete`로 확인합니다. 파일 크기만으로 판단하면 안 됩니다: 병렬 재개 다운로드는 미리 공간을 할당할 수 있습니다.

Littora 등 Roboflow 데이터는 다운로드 인증이 필요하며 아직 받지 못했습니다. 내려받은 것으로 표시하지 않습니다. 사진과 모델 배포 시 각 라이선스·출처를 유지해야 합니다.

## 프로토콜 출처 및 외부 구성요소

- WiFi UAV/FLOW 패킷 정보: https://github.com/marshallrichards/turbodrone/blob/main/docs/research/wifi_uav.md
- FLOW 영상 수신 호환성 참고: https://github.com/OpenIPC/decoder/blob/v2/docs/toys.md
- Chaquopy MIT, Python PSF, ONNX Runtime Web MIT. [외부 구성요소](docs/THIRD_PARTY.md).

