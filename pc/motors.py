"""Four wheel motors. Arduino runs existing StandardFirmata; our logic is Python."""
import math
import threading
import time

DIRECTIONS={"stop":(0,0),"forward":(1,1),"backward":(-1,-1),"left":(-1,1),"right":(1,-1)}


def mix(direction,speed):
    if direction not in DIRECTIONS:
        raise ValueError("Unknown direction")
    speed=float(speed)
    if not math.isfinite(speed) or not 0<=speed<=1:
        raise ValueError("Speed must be between 0 and 1")
    left,right=DIRECTIONS[direction]
    return [left*speed,left*speed,right*speed,right*speed]


class Motors:
    def __init__(self,settings):
        self.settings=settings
        self.board=None
        self.pins=[]
        self.lock=threading.Lock()
        self.values=[0.,0.,0.,0.]
        self.deadline=0.
        self.running=True
        self.error=""
        self.max_speed=float(settings.get("max_speed",.5))
        if not 0<self.max_speed<=1:
            raise ValueError("max_speed must be between 0 and 1")
        self.simulated=bool(settings.get("simulate",True))
        if not self.simulated:
            if not settings.get("driver_verified",False):
                raise ValueError("모터 드라이버와 배선을 확인한 뒤 driver_verified를 설정하세요.")
            self._connect()
        self.thread=threading.Thread(target=self._watchdog,daemon=True)
        self.thread.start()

    def _connect(self):
        from pyfirmata2 import Arduino
        definitions=self.settings["motors"]
        used=[]
        for item in definitions:
            used.extend([item["in1"],item["in2"],item["pwm"]])
            if item["pwm"] not in (3,5,6,9,10,11):
                raise ValueError("Uno/Nano PWM pin must be 3,5,6,9,10 or 11")
        if len(definitions)!=4 or len(set(used))!=12 or any(not 2<=n<=13 for n in used):
            raise ValueError("모터 4개에 서로 다른 D2~D13 핀 12개가 필요합니다.")
        self.board=Arduino(self.settings["port"])
        try:
            for item in definitions:
                self.pins.append((self.board.get_pin(f"d:{item['in1']}:o"),self.board.get_pin(f"d:{item['in2']}:o"),self.board.get_pin(f"d:{item['pwm']}:p"),bool(item.get("invert",False))))
            self._write([0.,0.,0.,0.])
        except Exception:
            self.board.exit()
            raise

    def _write(self,values):
        if self.board:
            # Remove PWM before direction changes, then apply the new duty cycle.
            for a,b,pwm,invert in self.pins:
                pwm.write(0)
            for value,(a,b,pwm,invert) in zip(values,self.pins):
                value=-value if invert else value
                a.write(int(value>0))
                b.write(int(value<0))
                pwm.write(abs(value))
        self.values=list(values)

    def drive(self,direction,speed):
        speed=float(speed)
        mix(direction,speed)  # Validate before clamping, including NaN and infinity.
        values=mix(direction,min(speed,self.max_speed))
        with self.lock:
            if self.error:
                raise RuntimeError(self.error)
            try:
                self._write(values)
                self.deadline=time.monotonic()+.35 if direction!="stop" else 0
            except Exception as exc:
                self.error=str(exc)
                try:
                    self._write([0.,0.,0.,0.])
                except Exception:
                    pass
                raise
        return self.state()

    def state(self):
        with self.lock:
            return {"simulated":self.simulated,"motors":list(self.values),"error":self.error}

    def _watchdog(self):
        while self.running:
            with self.lock:
                if self.deadline and time.monotonic()>self.deadline:
                    try:
                        self._write([0.,0.,0.,0.])
                    except Exception as exc:
                        self.error=str(exc)
                    self.deadline=0
            time.sleep(.02)

    def close(self):
        self.running=False
        with self.lock:
            try:
                self._write([0.,0.,0.,0.])
            finally:
                if self.board:
                    self.board.exit()
