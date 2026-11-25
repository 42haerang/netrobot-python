// UNO/Nano: 앞바퀴 DC 모터 2개 + SG90 집게 + USB/HC-06. 뒷바퀴 출력은 없습니다.
#include <SoftwareSerial.h>
#include <Servo.h>
#include <stdio.h>
#include <string.h>

// 사진에 나온 배선입니다. ENA/ENB의 항상 켜짐 점퍼는 빼고 D5/D6에 연결합니다.
const byte ENA = 5, IN1 = 7, IN2 = 8;
const byte ENB = 6, IN3 = 12, IN4 = 13;
const byte SERVO_PIN = 10;
const int LEFT_SIGN = 1, RIGHT_SIGN = 1;  // 뒤로 도는 바퀴만 -1로 바꾸세요.
const int MAX_PWM = 255;                 // Arduino PWM 전체 범위: 최대 출력 100%.
const int GRIP_CLOSED = 0, GRIP_OPEN = 180;  // 이전 70~110도 제한을 해제합니다.
const unsigned long TIMEOUT_MS = 600;
SoftwareSerial bluetooth(2, 4);         // Arduino RX=D2, TX=D4(분압 후 HC-06 RXD).
Servo gripper;

// 모듈의 UART 설정이 달라도 HELLO를 받은 속도로 고정합니다.
const unsigned long BT_BAUDS[] = {9600, 38400, 19200, 57600, 115200, 4800};
byte baudIndex = 0;
bool baudLocked = false;
unsigned long baudStarted = 0;

// 연결만으로는 움직이지 않습니다. ARM 명령 뒤 유효한 조종 명령이 필요합니다.
bool armed = false, overflow = false, usbOverflow = false;
char line[48], usbLine[48];
byte used = 0, usbUsed = 0;
Stream *controller = nullptr;
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
void command(char *text, Stream &reply) {
  if (strcmp(text, "HELLO") == 0) {
    stopAll();
    controller = &reply;
    if (&reply == &bluetooth) {
      baudLocked = true;
      Serial.print(F("HC06 LINK "));
      Serial.println(BT_BAUDS[baudIndex]);
    }
    reply.println(F("NETROBOT 1"));
  } else if (strcmp(text, "STOP") == 0) {
    stopAll();
    reply.println(F("STOPPED"));
  } else if (strcmp(text, "ARM") == 0) {
    stopAll();
    if (controller != &reply) {
      reply.println(F("DISARMED"));
      return;
    }
    if (!gripper.attached()) {
      gripper.write(gripAngle);
      gripper.attach(SERVO_PIN);
    }
    lastCommand = millis();
    armed = true;
    reply.println(F("ARMED"));
  } else {
    long left, right, grip;
    char extra;
    int count = sscanf(text, "D %ld %ld %ld %c", &left, &right, &grip, &extra);
    if (count != 3 || left < -MAX_PWM || left > MAX_PWM ||
        right < -MAX_PWM || right > MAX_PWM || grip < -1 || grip > 1) {
      stopAll();
      reply.println(F("ERROR"));
      return;
    }
    if (!armed || controller != &reply) {
      reply.println(F("DISARMED"));
      return;
    }
    motor(ENA, IN1, IN2, left * LEFT_SIGN);
    motor(ENB, IN3, IN4, right * RIGHT_SIGN);
    gripDirection = grip;
    lastCommand = millis();
    reply.print(F("OK "));
    reply.println(gripAngle);
  }
}

// 부팅할 때 바퀴는 정지 상태이고, 서보도 활성화 전에는 신호를 내보내지 않습니다.
void setup() {
  pinMode(ENA, OUTPUT); pinMode(ENB, OUTPUT);
  pinMode(IN1, OUTPUT); pinMode(IN2, OUTPUT);
  pinMode(IN3, OUTPUT); pinMode(IN4, OUTPUT);
  stopAll();
  Serial.begin(115200);
  Serial.println(F("NETROBOT READY - MOTORS DISARMED"));
  bluetooth.begin(BT_BAUDS[baudIndex]);
  baudStarted = millis();
}

// USB와 HC-06은 같은 명령을 쓰고, 각 입력의 줄 버퍼는 따로 보관합니다.
void readCommands(Stream &input, char *line, byte &used, bool &overflow) {
  while (input.available()) {
    char value = input.read();
    if (value == '\n') {
      if (!overflow) {
        line[used] = '\0';
        command(line, input);
      }
      used = 0;
      overflow = false;
    } else if (value != '\r') {
      if (used < 47 && !overflow) line[used++] = value;
      else { overflow = true; stopAll(); }
    }
  }
}

// 오래된 명령은 유지하지 않습니다. 긴 줄이나 통신 끊김은 정지로 처리합니다.
void loop() {
  // 인사 명령을 받기 전까지만 속도를 탐색하며 모터는 정지 상태입니다.
  if (!baudLocked && controller != &Serial && millis() - baudStarted >= 1200) {
    bluetooth.end();
    baudIndex = (baudIndex + 1) % (sizeof(BT_BAUDS) / sizeof(BT_BAUDS[0]));
    bluetooth.begin(BT_BAUDS[baudIndex]);
    used = 0;
    overflow = false;
    baudStarted = millis();
  }
  readCommands(Serial, usbLine, usbUsed, usbOverflow);
  readCommands(bluetooth, line, used, overflow);
  unsigned long now = millis();
  if (armed && now - lastCommand > TIMEOUT_MS) stopAll();

  // 누르는 동안 10ms마다 6도 명령으로 이동합니다. 실제 속도는 서보와 부하에 따릅니다.
  if (armed && gripDirection && now - lastGripStep >= 10) {
    gripAngle = constrain(gripAngle + gripDirection * 6, GRIP_CLOSED, GRIP_OPEN);
    gripper.write(gripAngle);
    lastGripStep = now;
  }
}
