"""Wheel and DC gripper controller. Simulation by default; Arduino uses StandardFirmata."""
import math
import threading
import time

DIRECTIONS={'stop':(0,0),'forward':(1,1),'backward':(-1,-1),'left':(-1,1),'right':(1,-1)}


def unit(value):
    value=float(value)
    if not math.isfinite(value) or not 0<=value<=1:
        raise ValueError('Speed must be between 0 and 1')
    return value


def mix(direction,speed):
    if direction not in DIRECTIONS:
        raise ValueError('Unknown direction')
    speed=unit(speed)
    left,right=DIRECTIONS[direction]
    return [left*speed,left*speed,right*speed,right*speed]


def mix_vector(x,y,speed):
    x,y,speed=float(x),float(y),unit(speed)
    if not math.isfinite(x) or not math.isfinite(y) or abs(x)>1 or abs(y)>1:
        raise ValueError('Joystick coordinates must be between -1 and 1')
    left,right=y+x,y-x
    scale=max(1,abs(left),abs(right))
    return [left/scale*speed,left/scale*speed,right/scale*speed,right/scale*speed]


class Motors:
    def __init__(self,settings):
        self.settings=settings
        self.board=None
        self.pins=[]
        self.gripper_pins=None
        self.lock=threading.Lock()
        self.values=[0.]*4
        self.gripper_value=0.
        self.deadline=self.gripper_deadline=self.gripper_started=0.
        self.gripper_action='stop'
        self.gripper_latched=False
        self.running=True
        self.error=''
        self.max_speed=unit(settings.get('max_speed',.5))
        self.gripper_speed=unit(settings.get('gripper_speed',.35))
        self.gripper_max_seconds=float(settings.get('gripper_max_seconds',2))
        if self.max_speed<=0 or not math.isfinite(self.gripper_max_seconds) or not .1<=self.gripper_max_seconds<=5:
            raise ValueError('Invalid speed or gripper time limit')
        self.simulated=bool(settings.get('simulate',True))
        if not self.simulated:
            if not settings.get('driver_verified',False):
                raise ValueError('모터 드라이버와 배선을 확인한 뒤 driver_verified를 설정하세요.')
            self._connect()
        self.thread=threading.Thread(target=self._watchdog,daemon=True)
        self.thread.start()

    def _connect(self):
        from pyfirmata2 import Arduino
        definitions=self.settings['motors']
        gripper=self.settings.get('gripper')
        if len(definitions)!=4 or not isinstance(gripper,dict):
            raise ValueError('바퀴 4개와 집게 1개의 모터 핀 설정이 필요합니다.')
        used=[]
        for item in [*definitions,gripper]:
            used.extend([item['in1'],item['in2'],item['pwm']])
            if item['pwm'] not in (3,5,6,9,10,11):
                raise ValueError('Uno/Nano PWM pin must be 3,5,6,9,10 or 11')
        if len(set(used))!=15 or any(not isinstance(n,int) or not 2<=n<=19 for n in used):
            raise ValueError('서로 다른 D2~D13, A0~A5(14~19) 핀 15개가 필요합니다.')
        self.board=Arduino(self.settings['port'])
        def pins(item):
            return (self.board.get_pin(f"d:{item['in1']}:o"),self.board.get_pin(f"d:{item['in2']}:o"),self.board.get_pin(f"d:{item['pwm']}:p"),bool(item.get('invert',False)))
        try:
            self.pins=[pins(item) for item in definitions]
            self.gripper_pins=pins(gripper)
            self._write([0.]*4)
            self._write_gripper(0)
        except Exception:
            self.board.exit()
            raise

    @staticmethod
    def _pin_write(pins,value):
        a,b,pwm,invert=pins
        value=-value if invert else value
        pwm.write(0)
        a.write(int(value>0))
        b.write(int(value<0))
        pwm.write(abs(value))

    def _write(self,values):
        if self.board:
            for value,pins in zip(values,self.pins):
                self._pin_write(pins,value)
        self.values=list(values)

    def _write_gripper(self,value):
        if self.board:
            self._pin_write(self.gripper_pins,value)
        self.gripper_value=value

    def _set_gripper(self,action):
        now=time.monotonic()
        if action=='stop':
            self.gripper_started=self.gripper_deadline=0
            self.gripper_latched=False
        elif not self.gripper_latched:
            if self.gripper_action!=action:
                self.gripper_started=now
            if now-self.gripper_started>=self.gripper_max_seconds:
                self.gripper_latched=True
            self.gripper_deadline=now+.35
        self.gripper_action=action
        value=0 if action=='stop' or self.gripper_latched else self.gripper_speed*(1 if action=='open' else -1)
        self._write_gripper(value)

    def _apply(self,values=None,gripper=None):
        if gripper is not None and gripper not in ('open','close','stop'):
            raise ValueError('Gripper action must be open, close or stop')
        with self.lock:
            if self.error:
                raise RuntimeError(self.error)
            try:
                if values is not None:
                    self._write(values)
                    self.deadline=time.monotonic()+.35 if any(values) else 0
                if gripper is not None:
                    self._set_gripper(gripper)
            except Exception as exc:
                self.error=str(exc)
                try:
                    self._write([0.]*4)
                    self._write_gripper(0)
                except Exception:
                    pass
                raise
        return self.state()

    def drive(self,direction,speed):
        return self._apply(mix(direction,min(unit(speed),self.max_speed)))

    def move(self,x,y,speed,gripper='stop'):
        return self._apply(mix_vector(x,y,min(unit(speed),self.max_speed)),gripper)

    def grip(self,action):
        return self._apply(gripper=action)

    def state(self):
        with self.lock:
            return {'simulated':self.simulated,'motors':list(self.values),'gripper':self.gripper_value,
                    'gripper_limit_reached':self.gripper_latched,'error':self.error}

    def _watchdog(self):
        while self.running:
            with self.lock:
                now=time.monotonic()
                try:
                    if self.deadline and now>self.deadline:
                        self._write([0.]*4)
                        self.deadline=0
                    if self.gripper_started and self.gripper_action!='stop' and now-self.gripper_started>=self.gripper_max_seconds:
                        self._write_gripper(0)
                        self.gripper_latched=True
                    if self.gripper_deadline and now>self.gripper_deadline:
                        self._write_gripper(0)
                        self.gripper_deadline=0
                        self.gripper_action='stop'
                        self.gripper_started=0
                except Exception as exc:
                    self.error=str(exc)
            time.sleep(.02)

    def close(self):
        self.running=False
        with self.lock:
            try:
                self._write([0.]*4)
                self._write_gripper(0)
            finally:
                if self.board:
                    self.board.exit()
