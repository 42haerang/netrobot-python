"""HC-06의 Windows Bluetooth COM 포트로 앞바퀴 2개와 SG90을 조종합니다."""

import threading
import time
import os
import re
import subprocess

import serial
from serial.tools import list_ports


# Bluetooth 직렬 포트만 표시합니다. 임의의 USB 장치에 명령을 보내지 않습니다.
def bluetooth_ports():
    # Windows가 표시한 HC-06의 장치 주소로 출력 포트 이름을 붙입니다.
    addresses = []
    if os.name == "nt":
        try:
            found = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-Command",
                    "Get-PnpDevice -Class Bluetooth -PresentOnly | Where-Object {$_.FriendlyName -eq 'HC-06'} | ForEach-Object {$_.InstanceId}",
                ],
                capture_output=True,
                timeout=6,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            addresses = re.findall(
                r"DEV_([0-9A-F]{12})", found.stdout.decode(errors="ignore"), re.I
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    result = []
    for port in list_ports.comports():
        text = f"{port.description} {port.hwid}"
        if "bluetooth" in text.lower() or "bthenum" in text.lower():
            matched = any(address.lower() in port.hwid.lower() for address in addresses)
            result.append(
                {
                    "port": port.device,
                    "description": f"HC-06 ({port.device})" if matched else port.description,
                    "hc06": matched,
                }
            )
    return sorted(result, key=lambda item: not item["hc06"])


# 모든 직렬 입출력은 잠금으로 보호해 HTTP 요청과 전송 스레드가 섞이지 않게 합니다.
class MotorLink:
    def __init__(self, opener=serial.Serial, ports=bluetooth_ports):
        self.opener, self.ports = opener, ports
        self.lock = threading.RLock()
        self.serial = None
        self.thread = None
        self.stop_event = threading.Event()
        self.port = ""
        self.armed = False
        self.error = ""
        self.values = (0, 0, 0)
        self.last_input = 0
        self.angle = None

    # 응답까지 확인한 명령만 성공으로 처리합니다.
    def exchange(self, command, expected, timeout=0.45):
        self.serial.write((command + "\n").encode("ascii"))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            answer = self.serial.readline(80).decode("ascii", errors="replace").strip()
            if answer == expected or (expected == "OK" and answer.startswith("OK ")):
                return answer
            if answer in ("ERROR", "DISARMED"):
                raise RuntimeError("아두이노가 명령을 거부했습니다. 다시 활성화하세요.")
        raise RuntimeError("아두이노 응답이 없습니다. 코드 업로드·9600 baud·출력 COM을 확인하세요.")

    # 펌웨어의 인사 응답을 받은 뒤에만 연결됨으로 표시합니다. 모터는 아직 비활성입니다.
    def connect(self, port):
        if port not in [item["port"] for item in self.ports()]:
            raise ValueError("목록에 있는 HC-06 Bluetooth COM 포트를 선택하세요.")
        self.disconnect()
        with self.lock:
            self.port = port
            try:
                self.serial = self.opener(port, 9600, timeout=0.06, write_timeout=0.2)
                # Windows SPP 연결 직후 첫 데이터가 늦어질 수 있어 인사를 다시 보냅니다.
                deadline = time.monotonic() + 12
                while True:
                    try:
                        self.exchange("HELLO", "NETROBOT 1", 0.8)
                        break
                    except RuntimeError:
                        if time.monotonic() >= deadline:
                            raise
                self.port, self.error = port, ""
                self.stop_event = threading.Event()
                self.thread = threading.Thread(target=self.run, daemon=True)
                self.thread.start()
            except Exception as error:
                self.error = str(error)
                if self.serial is not None:
                    self.serial.close()
                self.serial = None
                raise

    # 활성화는 사용자가 버튼을 눌렀을 때만 합니다. 자동 재연결로 다시 켜지지 않습니다.
    def arm(self):
        with self.lock:
            if self.serial is None:
                raise RuntimeError("HC-06을 먼저 연결하세요.")
            self.exchange("ARM", "ARMED")
            self.values = (0, 0, 0)
            self.last_input = time.monotonic()
            self.armed, self.error = True, ""

    # 바퀴 두 개와 집게 방향만 받습니다. 범위를 벗어난 명령은 보내지 않습니다.
    def command(self, left, right, grip):
        values = (left, right, grip)
        if any(type(value) is not int for value in values):
            raise ValueError("모터 명령은 정수여야 합니다.")
        if abs(left) > 153 or abs(right) > 153 or grip not in (-1, 0, 1):
            raise ValueError("모터 출력 범위가 잘못되었습니다.")
        with self.lock:
            if not self.armed or self.serial is None:
                raise RuntimeError("모터 활성화 버튼을 먼저 누르세요.")
            self.values, self.last_input = values, time.monotonic()

    # 놓기·긴급 정지·화면 이탈은 출력 0과 비활성화로 처리합니다.
    def stop(self):
        with self.lock:
            self.armed = False
            self.values = (0, 0, 0)
            if self.serial is not None:
                self.exchange("STOP", "STOPPED")

    # 브라우저의 새 입력이 0.4초 끊기면 정지합니다. Arduino에도 별도 0.6초 제한이 있습니다.
    def run(self):
        last_check = 0
        while not self.stop_event.wait(0.08):
            with self.lock:
                try:
                    if self.armed:
                        if time.monotonic() - self.last_input > 0.4:
                            self.stop()
                            self.error = "조종 신호가 끊겨 정지했습니다. 다시 활성화하세요."
                        else:
                            answer = self.exchange("D %d %d %d" % self.values, "OK")
                            self.angle = int(answer.split()[1])
                    elif time.monotonic() - last_check > 1:
                        self.exchange("HELLO", "NETROBOT 1")
                        last_check = time.monotonic()
                except Exception as error:
                    self.error = str(error)
                    self.armed = False
                    self.values = (0, 0, 0)
                    if self.serial is not None:
                        self.serial.close()
                    self.serial = None
                    return

    # 연결 종료 시에도 먼저 정지 명령을 보내고 포트를 닫습니다.
    def disconnect(self):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=1.2)
        with self.lock:
            try:
                self.stop()
            except Exception:
                pass
            if self.serial is not None:
                self.serial.close()
            self.serial = None
            self.armed = False
            self.values = (0, 0, 0)
            self.thread = None

    # 직렬 포트가 열린 것과 실제 펌웨어 응답이 확인된 연결을 구분합니다.
    def status(self):
        with self.lock:
            return {
                "connected": self.serial is not None,
                "armed": self.armed,
                "port": self.port,
                "error": self.error,
                "gripper_angle": self.angle,
                "left": self.values[0],
                "right": self.values[1],
            }
