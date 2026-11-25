"""Offline Android shell in Python: bundled web UI + direct WiFi UAV UDP video."""
import json
import mimetypes
from pathlib import PurePosixPath
from urllib.parse import urlsplit,parse_qs

from java import static_proxy,dynamic_proxy,Override,constructor,jvoid,jint,jboolean,jbyte,jarray
from java.lang import Runnable,String
from java.io import ByteArrayInputStream
from java.util import HashMap
from android.app import Activity
from android.os import Bundle
from android.content import Context,Intent
from android.provider import Settings
from android.net import NetworkCapabilities,Uri
from android.view import WindowManager
from android.webkit import WebView,WebViewClient,WebResourceRequest,WebResourceResponse,WebChromeClient,ValueCallback,WebSettings
from flow_video import Receiver

ORIGIN='https://appassets.androidplatform.net'


class Task(dynamic_proxy(Runnable)):
    def __init__(self,function):
        super().__init__()
        self.function=function
    def run(self):self.function()


class Client(static_proxy(WebViewClient)):
    @constructor([])
    def __init__(self):
        super().__init__()
        self.owner=None

    @Override(WebResourceResponse,[WebView,WebResourceRequest])
    def shouldInterceptRequest(self,view,request):
        try:
            url=str(request.getUrl())
            parsed=urlsplit(url)
            if parsed.scheme!='https' or parsed.netloc!='appassets.androidplatform.net':
                return self.response(b'Blocked external request','text/plain',403)
            if str(request.getMethod())!='GET':
                return self.response(b'GET only','text/plain',405)
            if parsed.path.startswith('/native/'):
                return self.native(parsed.path,parse_qs(parsed.query))
            path=parsed.path.lstrip('/') or 'index.html'
            if '..' in PurePosixPath(path).parts or '\\' in path:
                return self.response(b'Not found','text/plain',404)
            mime={'.js':'text/javascript','.mjs':'text/javascript','.wasm':'application/wasm','.css':'text/css','.html':'text/html','.svg':'image/svg+xml','.json':'application/json','.onnx':'application/octet-stream'}.get(PurePosixPath(path).suffix,'application/octet-stream')
            try:
                stream=self.owner.getAssets().open('web/'+path)
                return WebResourceResponse(mime,'UTF-8' if mime.startswith(('text/','application/json','image/svg')) else None,stream)
            except Exception:
                return self.response(b'Not found','text/plain',404)
        except Exception as exc:
            return self.response(json.dumps({'error':str(exc)}).encode(),'application/json',500)

    @Override(jboolean,[WebView,WebResourceRequest])
    def shouldOverrideUrlLoading(self,view,request):
        return not str(request.getUrl()).startswith(ORIGIN+'/')

    def response(self,data,mime='application/json',status=200,headers=None):
        stream=ByteArrayInputStream(jarray(jbyte)(data))
        response=WebResourceResponse(mime,'UTF-8' if mime.startswith(('text/','application/json')) else None,stream)
        if status!=200:response.setStatusCodeAndReasonPhrase(status,'Error')
        response_headers=HashMap()
        for key,value in {'Cache-Control':'no-store',**(headers or {})}.items():
            response_headers.put(key,value)
        response.setResponseHeaders(response_headers)
        return response

    def native(self,path,query):
        receiver=self.owner.receiver
        if path=='/native/connect':
            host=query.get('host',['192.168.169.1'])[0]
            mode=query.get('mode',['zigzag'])[0]
            self.owner.bind_wifi()
            receiver.connect(host,mode)
            return self.response(json.dumps({'ok':True,'simulated':True,'host':host}).encode())
        if path=='/native/disconnect':
            receiver.close()
            return self.response(b'{"ok":true}')
        if path=='/native/wifi':
            self.owner.runOnUiThread(Task(lambda:self.owner.startActivity(Intent(Settings.ACTION_WIFI_SETTINGS))))
            return self.response(b'{"ok":true}')
        if path=='/native/status':
            import time
            with receiver.lock:
                ready=receiver.jpeg is not None and time.monotonic()-receiver.timestamp<1.5
                data={'ready':ready,'error':receiver.error,'sequence':receiver.sequence,'port':receiver.port,'simulated':True}
            return self.response(json.dumps(data,ensure_ascii=False).encode())
        if path=='/native/frame.jpg':
            frame,sequence=receiver.frame()
            if frame is None:return self.response(b'{"error":"No drone frame yet"}',status=503)
            return self.response(frame,'image/jpeg',headers={'X-Frame-Sequence':str(sequence)})
        return self.response(b'Not found','text/plain',404)


class Chrome(static_proxy(WebChromeClient)):
    @constructor([])
    def __init__(self):
        super().__init__()
        self.owner=None

    @Override(jboolean,[WebView,ValueCallback,WebChromeClient.FileChooserParams])
    def onShowFileChooser(self,view,callback,params):
        if self.owner.file_callback is not None:self.owner.file_callback.onReceiveValue(None)
        self.owner.file_callback=callback
        intent=Intent(Intent.ACTION_OPEN_DOCUMENT)
        intent.addCategory(Intent.CATEGORY_OPENABLE)
        intent.setType('*/*')
        self.owner.startActivityForResult(intent,7337)
        return True


class MainActivity(static_proxy(Activity)):
    @Override(jvoid,[Bundle])
    def onCreate(self,bundle):
        Activity.onCreate(self,bundle)
        self.file_callback=None
        self.getWindow().addFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN|WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        self.getWindow().getDecorView().setSystemUiVisibility(5894)
        self.receiver=Receiver(self.load_header)
        self.web=WebView(self)
        self.client=Client()
        self.client.owner=self
        self.chrome=Chrome()
        self.chrome.owner=self
        self.web.setWebViewClient(self.client)
        self.web.setWebChromeClient(self.chrome)
        settings=self.web.getSettings()
        settings.setJavaScriptEnabled(True)
        settings.setDomStorageEnabled(True)
        settings.setCacheMode(WebSettings.LOAD_NO_CACHE)
        self.web.clearCache(True)  # APK upgrades must load the new packaged JS/model manifest.
        settings.setAllowFileAccess(False)
        settings.setAllowContentAccess(True)  # SAF model file chooser, not arbitrary filesystem URLs.
        settings.setMediaPlaybackRequiresUserGesture(False)
        settings.setSupportZoom(False)
        self.setContentView(self.web)
        self.web.loadUrl(ORIGIN+'/index.html')

    def load_header(self,quality):
        source=self.getAssets().open(f'jpeg_headers/q{quality:03d}.bin')
        buffer=jarray(jbyte)(1024)
        result=bytearray()
        try:
            while True:
                count=source.read(buffer)
                if count<0:break
                result.extend(bytes(buffer)[:count])
        finally:source.close()
        return bytes(result)

    def bind_wifi(self):
        manager=self.getSystemService(Context.CONNECTIVITY_SERVICE)
        for network in manager.getAllNetworks():
            capabilities=manager.getNetworkCapabilities(network)
            if capabilities is not None and capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI):
                manager.bindProcessToNetwork(network)
                return
        raise RuntimeError('먼저 휴대폰을 FLOW_27AF9C Wi-Fi에 연결하세요.')

    @Override(jvoid,[jint,jint,Intent])
    def onActivityResult(self,request_code,result_code,data):
        Activity.onActivityResult(self,request_code,result_code,data)
        if request_code==7337 and self.file_callback is not None:
            result=jarray(Uri)([data.getData()]) if result_code==Activity.RESULT_OK and data is not None else None
            self.file_callback.onReceiveValue(result)
            self.file_callback=None

    @Override(jvoid,[])
    def onPause(self):
        if hasattr(self,'receiver'):self.receiver.close()
        if hasattr(self,'web'):
            self.web.evaluateJavascript('window.netrobotPause?.()',None)
            self.web.onPause()
        Activity.onPause(self)

    @Override(jvoid,[])
    def onResume(self):
        Activity.onResume(self)
        if hasattr(self,'web'):
            self.web.onResume()
            self.web.evaluateJavascript('window.netrobotResume?.()',None)

    @Override(jvoid,[])
    def onDestroy(self):
        if hasattr(self,'receiver'):self.receiver.close()
        if hasattr(self,'web'):self.web.destroy()
        Activity.onDestroy(self)

