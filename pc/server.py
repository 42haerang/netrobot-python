"""Laptop: webcam JPEGs and USB Arduino bridge. No YOLO computation here."""
from pathlib import Path
import atexit
import hmac
import io
import json
import secrets
import socket
import threading
import time
import zipfile

import cv2
from flask import Flask,Response,abort,jsonify,request,send_file,send_from_directory
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
    web=ROOT/'web'
    allowed_origins=set(settings.get('web_origins',[
        'https://netrobot-control-42h.lush-quail-0027.chatgpt.site',
        'https://42haerang.github.io',
        'http://127.0.0.1:5173','http://localhost:5173']))
    pair_attempts={}
    session={'id':None,'sequence':-1}
    command_lock=threading.Lock()

    def public_asset():
        path=(web/request.path.lstrip('/')).resolve()
        return path.is_relative_to(web.resolve()) and path.is_file()

    def camera_ready():
        with camera.lock:
            return camera.jpeg is not None and time.monotonic()-camera.timestamp<1

    def net_model_ready():
        folder=ROOT/'phone/models'
        try:
            return (folder/'net.onnx').is_file() and json.loads((folder/'model.json').read_text(encoding='utf-8')).get('trained_on_net') is True
        except (OSError,ValueError):
            return False

    @app.before_request
    def authorize():
        origin=request.headers.get('Origin')
        if origin and origin not in allowed_origins and origin!=request.host_url.rstrip('/'):
            abort(403)
        if request.method=='OPTIONS':
            return Response(status=204)
        if request.path in ('/','/health','/phone.zip','/pair') or (request.method=='GET' and public_asset()):
            return
        provided=request.headers.get('X-Control-Token','')
        if not provided or not hmac.compare_digest(provided,token):
            abort(401)

    @app.after_request
    def response_headers(response):
        origin=request.headers.get('Origin')
        if origin and (origin in allowed_origins or origin==request.host_url.rstrip('/')):
            response.headers['Access-Control-Allow-Origin']=origin
            response.headers['Vary']='Origin'
            response.headers['Access-Control-Allow-Headers']='Content-Type, X-Control-Token'
            response.headers['Access-Control-Allow-Methods']='GET, POST, OPTIONS'
            response.headers['Access-Control-Expose-Headers']='X-Frame-Sequence'
        response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        return response

    @app.get('/')
    def index():
        return send_from_directory(web,'index.html')

    @app.get('/<path:filename>')
    def web_asset(filename):
        # Windows MIME registry can label .mjs as text/plain; browsers reject it.
        types={'.js':'text/javascript','.mjs':'text/javascript','.wasm':'application/wasm'}
        return send_from_directory(web,filename,mimetype=types.get(Path(filename).suffix))

    @app.post('/pair')
    def pair():
        data=request.get_json(silent=True)
        if not isinstance(data,dict):
            return jsonify(error='JSON object required'),400
        now=time.monotonic()
        address=request.remote_addr or 'unknown'
        with command_lock:
            attempts=[t for t in pair_attempts.get(address,[]) if now-t<60]
            if len(attempts)>=8:
                return jsonify(error='Too many attempts; retry in one minute'),429
            attempts.append(now)
            pair_attempts[address]=attempts
            if not hmac.compare_digest(str(data.get('code','')),settings['pairing_code']):
                return jsonify(error='Invalid pairing code'),401
            motors.move(0,0,0,'stop')
            session.update(id=secrets.token_hex(16),sequence=-1)
            return jsonify(token=token,session=session['id'],simulated=motors.simulated,net_model_available=net_model_ready())

    @app.post('/drive')
    def drive():
        data=request.get_json(silent=True)
        if not isinstance(data,dict):
            return jsonify(error='JSON object required'),400
        try:
            with command_lock:
                if not session['id'] or not hmac.compare_digest(str(data.get('session','')),session['id']):
                    return jsonify(error='Pair again to control the robot'),401
                sequence=data.get('sequence')
                if not isinstance(sequence,int) or isinstance(sequence,bool) or sequence<0:
                    raise ValueError('Non-negative command sequence required')
                if sequence<=session['sequence']:
                    return jsonify(**motors.state(),ignored_stale_command=True)
                # Stop even if the caller requests motion while video has gone stale.
                if not camera_ready():
                    session['sequence']=sequence
                    motors.move(0,0,0,'stop')
                    return jsonify(error='Live camera is not available'),409
                result=motors.move(data.get('x',0),data.get('y',0),data.get('speed',0),data.get('gripper','stop'))
                session['sequence']=sequence
                return jsonify(result)
        except (ValueError,TypeError,OverflowError) as exc:
            return jsonify(error=str(exc)),400
        except Exception as exc:
            return jsonify(error=str(exc)),503

    @app.post('/gripper')
    def gripper():
        data=request.get_json(silent=True)
        if not isinstance(data,dict):
            return jsonify(error='JSON object required'),400
        action=data.get('action','stop')
        try:
            if action!='stop' and not camera_ready():
                motors.grip('stop')
                return jsonify(error='Live camera is not available'),409
            return jsonify(motors.grip(action))
        except (ValueError,TypeError,OverflowError) as exc:
            return jsonify(error=str(exc)),400
        except Exception as exc:
            return jsonify(error=str(exc)),503

    @app.get('/net-model.onnx')
    def net_model():
        if not net_model_ready():
            return jsonify(error='A net-trained ONNX model is not available yet'),404
        return send_file(ROOT/'phone/models/net.onnx',mimetype='application/octet-stream')

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
    print(f"노트북 웹 화면: http://127.0.0.1:{port}/#pair={settings['pairing_code']}",flush=True)
    print(f"휴대폰 웹 화면: http://{local_ip()}:{port}/#pair={settings['pairing_code']}",flush=True)
    print('연결 코드:',settings['pairing_code'],flush=True)
    print('그물 모델을 연결하면 브라우저에서 추론합니다. 모터 모드:', '모의 조종' if settings['controller']['simulate'] else '실제 Arduino',flush=True)
    app.run(host='0.0.0.0',port=port,threaded=True,use_reloader=False)
