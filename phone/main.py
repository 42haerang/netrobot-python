"""Legacy desktop preview. The requested Android UI source is android_main.py."""
from pathlib import Path
import json
import threading
import time

import cv2
import numpy as np
import requests
from kivy.app import App
from kivy.clock import Clock
from kivy.core.text import LabelBase
from kivy.core.window import Window
from kivy.graphics.texture import Texture
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.slider import Slider
from kivy.uix.textinput import TextInput
from kivy.utils import platform

from detector import Detector,draw

HERE=Path(__file__).resolve().parent
FONT=HERE/'fonts/NotoSansKR-Regular.otf'
if FONT.is_file():
    LabelBase.register(name='Korean',fn_regular=str(FONT))
FONT_NAME='Korean' if FONT.is_file() else 'Roboto'
BG=(.05,.08,.12,1)
GREEN=(.22,.75,.51,1)


class NetRobot(App):
    def build(self):
        Window.clearcolor=BG
        if platform!='android':
            Window.size=(450,850)
        self.title='NetRobot · 휴대폰 YOLO'
        self.running=True
        self.connected=False
        self.direction='stop'
        self.speed=.35
        self.token=''
        self.server=''
        self.last_frame=0.
        self.output=None
        self.info='노트북 서버 주소를 확인하고 연결하세요.'
        self.lock=threading.Lock()
        self.connection=threading.Event()
        self.network_thread=None
        self.control_thread=None
        self.detector=None
        config={}
        if (HERE/'config.json').exists():
            config=json.loads((HERE/'config.json').read_text(encoding='utf-8'))
        self.token=config.get('token','')
        root=BoxLayout(orientation='vertical',padding=dp(12),spacing=dp(6))
        root.add_widget(self.text('NETROBOT / PYTHON',size_hint_y=None,height=dp(30),font_size=dp(20),bold=True))
        address_row=BoxLayout(size_hint_y=None,height=dp(45),spacing=dp(6))
        self.address=TextInput(text=config.get('server','http://192.168.0.10:8765'),multiline=False,font_size=dp(16),font_name=FONT_NAME)
        address_row.add_widget(self.address)
        self.connect_button=self.button('연결',self.connect)
        self.connect_button.size_hint_x=.3
        address_row.add_widget(self.connect_button)
        root.add_widget(address_row)
        self.video=Image(fit_mode='contain')
        root.add_widget(self.video)
        self.status=self.text('',size_hint_y=None,height=dp(48),font_size=dp(14),halign='center')
        root.add_widget(self.status)
        self.model_label=self.text('YOLO: 휴대폰 자체 연산',size_hint_y=None,height=dp(26),font_size=dp(14))
        root.add_widget(self.model_label)
        speed_row=BoxLayout(size_hint_y=None,height=dp(30))
        speed_row.add_widget(self.text('속도',size_hint_x=.2))
        slider=Slider(min=.1,max=.5,value=.35)
        slider.bind(value=lambda _,value:setattr(self,'speed',float(value)))
        speed_row.add_widget(slider)
        root.add_widget(speed_row)
        controls=GridLayout(cols=3,size_hint_y=None,height=dp(150),spacing=dp(7))
        for caption,direction in [('',None),('전진','forward'),('',None),('좌회전','left'),('정지','stop'),('우회전','right'),('',None),('후진','backward'),('',None)]:
            if direction is None:
                controls.add_widget(self.text(''))
            else:
                btn=Button(text=caption,font_name=FONT_NAME,font_size=dp(18),background_normal='',background_color=(.75,.18,.24,1) if direction=='stop' else (.15,.26,.38,1))
                btn.bind(on_press=lambda _,d=direction:self.set_direction(d))
                btn.bind(on_release=lambda _:self.set_direction('stop'))
                controls.add_widget(btn)
        root.add_widget(controls)
        root.add_widget(self.text('방향 버튼은 누르는 동안만 동작 · 영상/통신 끊김 시 정지',size_hint_y=None,height=dp(30),font_size=dp(12)))
        Clock.schedule_interval(self.refresh,1/20)
        return root

    def text(self,value,**kwargs):
        return Label(text=value,font_name=FONT_NAME,color=(.9,.95,1,1),**kwargs)

    def button(self,value,callback):
        btn=Button(text=value,font_name=FONT_NAME,font_size=dp(17),background_normal='',background_color=GREEN)
        btn.bind(on_release=callback)
        return btn

    def connect(self,_button=None):
        if self.connected:
            self.disconnect()
            return
        if self.network_thread and self.network_thread.is_alive():
            self.info='이전 연결을 해제하고 있습니다. 잠시 후 다시 누르세요.'
            return
        if not self.token:
            self.info='PC가 안내하는 phone.zip을 받아 압축을 풀면 연결 코드가 포함됩니다.'
            return
        self.server=self.address.text.strip().rstrip('/')
        if not self.server.startswith('http://'):
            self.info='같은 Wi-Fi의 노트북 주소(http://...)를 입력하세요.'
            return
        self.direction='stop'
        self.last_frame=0
        self.connection=threading.Event()
        self.connection.set()
        self.connected=True
        self.connect_button.text='연결 끊기'
        self.info='카메라 연결 및 휴대폰 모델 준비 중…'
        self.network_thread=threading.Thread(target=self.read_and_detect,daemon=True)
        self.control_thread=threading.Thread(target=self.send_controls,daemon=True)
        self.network_thread.start()
        self.control_thread.start()

    def disconnect(self):
        self.direction='stop'
        self.connection.clear()
        self.connected=False
        self.connect_button.text='연결'
        self.info='연결을 끊었습니다.'

    def set_direction(self,direction):
        if direction!='stop' and (not self.connected or time.monotonic()-self.last_frame>1):
            self.info='실시간 영상이 연결된 상태에서 조종하세요.'
            self.direction='stop'
            return
        self.direction=direction

    def read_and_detect(self):
        connection=self.connection
        server,token=self.server,self.token
        model_error=''
        try:
            self.detector=Detector(HERE/'models')
        except Exception as exc:
            model_error='모델 오류: '+str(exc)
        session=requests.Session()
        headers={'X-Control-Token':token}
        previous=-1
        try:
            while self.running and connection.is_set():
                try:
                    response=session.get(server+'/frame.jpg',headers=headers,timeout=2)
                    response.raise_for_status()
                    sequence=int(response.headers.get('X-Frame-Sequence','0'))
                    if sequence==previous:
                        time.sleep(.03)
                        continue
                    previous=sequence
                    frame=cv2.imdecode(np.frombuffer(response.content,np.uint8),cv2.IMREAD_COLOR)
                    if frame is None:
                        raise ValueError('Invalid JPEG frame')
                    self.last_frame=time.monotonic()
                    start=time.monotonic()
                    results=self.detector.predict(frame) if self.detector else []
                    image=draw(frame,results)
                    elapsed=time.monotonic()-start
                    if model_error:
                        message=model_error
                    else:
                        message=' / '.join(f"{r['name']} {r['score']:.0%}" for r in results) or '감지된 그물 없음'
                        message+=f' · 휴대폰 추론 {elapsed*1000:.0f}ms'
                        if not self.detector.info.get('trained_on_net',False):
                            message='일반 모델 테스트(그물 미학습) · '+message
                    with self.lock:
                        self.output=image
                        self.info=message
                except Exception as exc:
                    self.direction='stop'
                    self.info='영상 수신 오류: '+str(exc)
                    time.sleep(.3)
        finally:
            self.direction='stop'
            session.close()

    def send_controls(self):
        connection=self.connection
        server,token=self.server,self.token
        session=requests.Session()
        simulated=True
        try:
            while self.running and connection.is_set():
                direction=self.direction
                if time.monotonic()-self.last_frame>1:
                    direction='stop'
                    self.direction='stop'
                try:
                    response=session.post(server+'/control',json={'direction':direction,'speed':self.speed},headers={'X-Control-Token':token},timeout=.6)
                    response.raise_for_status()
                    simulated=response.json().get('simulated',True)
                    self.simulated=simulated
                except requests.RequestException:
                    self.direction='stop'
                time.sleep(.1)
        finally:
            try:
                session.post(server+'/control',json={'direction':'stop','speed':0},headers={'X-Control-Token':token},timeout=.6)
            except requests.RequestException:
                pass
            session.close()

    def refresh(self,_dt):
        with self.lock:
            frame=self.output
            self.output=None
            text=self.info
        self.status.text=text
        self.status.text_size=(self.status.width,None)
        model_status='모의 조종' if getattr(self,'simulated',True) else '실제 Arduino 제어'
        self.model_label.text='YOLO: 휴대폰 자체 연산 · '+model_status
        if frame is not None:
            texture=Texture.create(size=(frame.shape[1],frame.shape[0]),colorfmt='bgr')
            texture.blit_buffer(np.flipud(frame).tobytes(),colorfmt='bgr',bufferfmt='ubyte')
            self.video.texture=texture
        if self.last_frame and time.monotonic()-self.last_frame>1:
            self.direction='stop'

    def on_pause(self):
        self.disconnect()
        return True

    def on_stop(self):
        self.direction='stop'
        self.running=False
        self.connection.clear()


if __name__=='__main__':
    NetRobot().run()
