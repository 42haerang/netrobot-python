"""Laptop: webcam JPEGs and USB Arduino bridge. No YOLO computation here."""
from pathlib import Path
import atexit
import hmac
import io
import json
import socket
import threading
import time
import zipfile

import cv2
from flask import Flask,Response,abort,jsonify,request,send_file
from motors import Motors

ROOT=Path(__file__).resolve().parents[1]


class Camera:
    def __init__(self,index=0):
        self.index=index
        self.jpeg=None
        self.timestamp=0.
        self.sequence=0
        self.error="카메라 연결 중"
        self.running=True
        self.lock=threading.Lock()
        self.thread=threading.Thread(target=self._run,daemon=True)
        self.thread.start()

    def _run(self):
        cap=None
        try:
            cap=cv2.VideoCapture(self.index,cv2.CAP_DSHOW if __import__('os').name=='nt' else cv2.CAP_ANY)
            if not cap.isOpened():
                raise RuntimeError("카메라를 열 수 없습니다. 다른 카메라 앱을 닫으세요.")
            cap.set(cv2.CAP_PROP_FRAME_WIDTH,640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT,480)
            failed=0
            while self.running:
                ok,frame=cap.read()
                if not ok:
                    failed+=1
                    if failed>20:
                        raise RuntimeError("카메라 연결이 끊겼습니다.")
                    time.sleep(.03)
                    continue
                failed=0
                ok,encoded=cv2.imencode('.jpg',frame,[cv2.IMWRITE_JPEG_QUALITY,72])
                if ok:
                    with self.lock:
                        self.jpeg=encoded.tobytes()
                        self.timestamp=time.monotonic()
                        self.sequence+=1
                        self.error=""
        except Exception as exc:
            with self.lock:
                self.error=str(exc)
        finally:
            if cap is not None:
                cap.release()

    def close(self):
        self.running=False


def create_app(settings,camera=None,motors=None):
    app=Flask(__name__)
    camera=camera or Camera(settings.get('camera',0))
    motors=motors or Motors(settings['controller'])
    token=settings['control_token']
    app.config.update(camera=camera,motors=motors)

    @app.before_request
    def authorize():
        if request.path in ('/health','/phone.zip'):
            return
        provided=request.headers.get('X-Control-Token','')
        if not provided or not hmac.compare_digest(provided,token):
            abort(401)

    @app.get('/health')
    def health():
        with camera.lock:
            ready=camera.jpeg is not None and time.monotonic()-camera.timestamp<1
            error=camera.error
        return jsonify(camera_ready=ready,camera_error=error,**motors.state())

    @app.get('/frame.jpg')
    def frame():
        with camera.lock:
            if camera.jpeg is None or time.monotonic()-camera.timestamp>1:
                return jsonify(error=camera.error or 'Camera frame is stale'),503
            image,sequence=camera.jpeg,camera.sequence
        return Response(image,mimetype='image/jpeg',headers={'Cache-Control':'no-store','X-Frame-Sequence':str(sequence)})

    @app.post('/control')
    def control():
        data=request.get_json(silent=True)
        if not isinstance(data,dict):
            return jsonify(error='JSON object required'),400
        try:
            with camera.lock:
                ready=camera.jpeg is not None and time.monotonic()-camera.timestamp<1
            direction=data.get('direction','stop')
            if direction!='stop' and not ready:
                motors.drive('stop',0)
                return jsonify(error='Live camera is not available'),409
            return jsonify(motors.drive(direction,data.get('speed',0)))
        except (ValueError,TypeError,OverflowError) as exc:
            return jsonify(error=str(exc)),400
        except Exception as exc:
            return jsonify(error=str(exc)),503

    @app.get('/phone.zip')
    def phone_bundle():
        # The pairing token is delivered only after entering the same code shown on the PC.
        if not hmac.compare_digest(request.args.get('code',''),settings['pairing_code']):
            abort(401)
        host=local_ip()
        config={'server':f'http://{host}:{settings.get("port",8765)}','token':token}
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
            for path in (ROOT/'phone').rglob('*'):
                if path.is_file() and '__pycache__' not in path.parts and path.name!='config.json':
                    archive.write(path,'phone/'+str(path.relative_to(ROOT/'phone')).replace('\\','/'))
            archive.writestr('phone/config.json',json.dumps(config))
        output.seek(0)
        return send_file(output,mimetype='application/zip',as_attachment=True,download_name='NetRobot_phone.zip')

    return app


def local_ip():
    try:
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
            sock.connect(('192.0.2.1',80))
            return sock.getsockname()[0]
    except OSError:
        return '127.0.0.1'


if __name__=='__main__':
    settings=json.loads((ROOT/'settings.json').read_text(encoding='utf-8'))
    app=create_app(settings)
    atexit.register(app.config['camera'].close)
    atexit.register(app.config['motors'].close)
    port=settings.get('port',8765)
    print('\n노트북과 휴대폰을 같은 Wi-Fi에 연결하세요.',flush=True)
    print(f"휴대폰 파일 받기: http://{local_ip()}:{port}/phone.zip?code={settings['pairing_code']}",flush=True)
    print('YOLO는 휴대폰에서 실행합니다. 모터 모드:', '모의 조종' if settings['controller']['simulate'] else '실제 Arduino',flush=True)
    app.run(host='0.0.0.0',port=port,threaded=True,use_reloader=False)
