// UNO/Nano: 앞바퀴 DC 모터 2개 + SG90 집게 + HC-06. 뒷바퀴 출력은 없습니다.
#include <SoftwareSerial.h>
#include <Servo.h>
#include <stdio.h>
#include <string.h>

// 사진에 나온 배선입니다. ENA/ENB의 항상 켜짐 점퍼는 빼고 D5/D6에 연결합니다.
const byte ENA = 5, IN1 = 7, IN2 = 8;
const byte ENB = 6, IN3 = 12, IN4 = 13;
const byte SERVO_PIN = 10;
const int LEFT_SIGN = 1, RIGHT_SIGN = 1;  // 뒤로 도는 바퀴만 -1로 바꾸세요.
const int MAX_PWM = 153;                 // 첫 시험은 최대 출력 60%로 제한합니다.
const int GRIP_CLOSED = 70, GRIP_OPEN = 110;
const unsigned long TIMEOUT_MS = 600;
SoftwareSerial bluetooth(2, 4);         // Arduino RX=D2, TX=D4(분압 후 HC-06 RXD).
Servo gripper;

// 연결만으로는 움직이지 않습니다. ARM 명령 뒤 유효한 조종 명령이 필요합니다.
bool armed = false, overflow = false;
char line[48];
byte used = 0;
int gripAngle = 90, gripDirection = 0;
unsigned long lastCommand = 0, lastGripStep = 0;

// 방향을 바꾸기 전에 출력을 끄고, 두 방향 핀과 PWM을 설정합니다.
void motor(byte enable, byte first, byte second, int value) {
  analogWrite(enable, 0);
  digitalWrite(first, value > 0 ? HIGH : LOW);
  digitalWrite(second, value < 0 ? HIGH : LOW);
  analogWrite(enable, abs(value));
}

// 정지하면 두 바퀴 출력을 끄고 집게의 추가 움직임을 멈춥니다.
void stopAll() {
  armed = false;
  gripDirection = 0;
  motor(ENA, IN1, IN2, 0);
  motor(ENB, IN3, IN4, 0);
}

// 줄 단위 명령만 처리합니다. 잘못된 명령으로 모터가 켜지지는 않습니다.
void command(char *text) {
  if (strcmp(text, "HELLO") == 0) {
    stopAll();
    bluetooth.println(F("NETROBOT 1"));
  } else if (strcmp(text, "STOP") == 0) {
    stopAll();
    bluetooth.println(F("STOPPED"));
  } else if (strcmp(text, "ARM") == 0) {
    stopAll();
    if (!gripper.attached()) {
      gripper.write(gripAngle);
      gripper.attach(SERVO_PIN);
    }
    lastCommand = millis();
    armed = true;
    bluetooth.println(F("ARMED"));
  } else {
    long left, right, grip;
    char extra;
    int count = sscanf(text, "D %ld %ld %ld %c", &left, &right, &grip, &extra);
    if (count != 3 || left < -MAX_PWM || left > MAX_PWM ||
        right < -MAX_PWM || right > MAX_PWM || grip < -1 || grip > 1) {
      stopAll();
      bluetooth.println(F("ERROR"));
      return;
    }
    if (!armed) {
      bluetooth.println(F("DISARMED"));
      return;
    }
    motor(ENA, IN1, IN2, left * LEFT_SIGN);
    motor(ENB, IN3, IN4, right * RIGHT_SIGN);
    gripDirection = grip;
    lastCommand = millis();
    bluetooth.print(F("OK "));
    bluetooth.println(gripAngle);
  }
}

// 부팅할 때 바퀴는 정지 상태이고, 서보도 활성화 전에는 신호를 내보내지 않습니다.
void setup() {
  pinMode(ENA, OUTPUT); pinMode(ENB, OUTPUT);
  pinMode(IN1, OUTPUT); pinMode(IN2, OUTPUT);
  pinMode(IN3, OUTPUT); pinMode(IN4, OUTPUT);
  stopAll();
  bluetooth.begin(9600);
}

// 오래된 명령은 유지하지 않습니다. 긴 줄이나 통신 끊김은 정지로 처리합니다.
void loop() {
  while (bluetooth.available()) {
    char value = bluetooth.read();
    if (value == '\n') {
      if (!overflow) {
        line[used] = '\0';
        command(line);
      }
      used = 0;
      overflow = false;
    } else if (value != '\r') {
      if (used < sizeof(line) - 1 && !overflow) line[used++] = value;
      else { overflow = true; stopAll(); }
    }
  }
  unsigned long now = millis();
  if (armed && now - lastCommand > TIMEOUT_MS) stopAll();

  // 집게 버튼을 누르는 동안만 천천히 움직이고, 놓으면 그 각도를 유지합니다.
  if (armed && gripDirection && now - lastGripStep >= 30) {
    gripAngle = constrain(gripAngle + gripDirection, GRIP_CLOSED, GRIP_OPEN);
    gripper.write(gripAngle);
    lastGripStep = now;
  }
}
