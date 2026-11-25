"""GitHub 화면과 오프라인 화면, 드론 영상을 연결하는 Android Python 코드."""

import hashlib
from base64 import b64decode
import json
import re
import threading
from pathlib import PurePosixPath
from urllib.parse import urlsplit, parse_qs, unquote
from urllib.request import urlopen

from java import (
    static_proxy,
    dynamic_proxy,
    Override,
    constructor,
    jvoid,
    jint,
    jboolean,
    jbyte,
    jarray,
)
from java.lang import Runnable, String
from java.io import ByteArrayInputStream
from java.util import HashMap
from android.app import Activity
from android.os import Bundle
from android.content import Context, Intent
from android.provider import Settings
from android.net import NetworkCapabilities, Uri
from android.view import WindowManager
from android.webkit import (
    WebView,
    WebViewClient,
    WebResourceRequest,
    WebResourceResponse,
    WebChromeClient,
    ValueCallback,
    WebSettings,
)
from flow_video import Receiver

# 이 GitHub 프로젝트 안에서만 앱의 영상 수신 기능을 사용할 수 있습니다.
SITE = "https://42haerang.github.io/netrobot-python/"


# 주소에 다른 호스트나 상위 폴더가 들어오면 거부합니다.
def site_path(url):
    parsed = urlsplit(url)
    base = urlsplit(SITE)
    if parsed.scheme != "https" or parsed.netloc != base.netloc:
        return None
    path = unquote(parsed.path)
    if not path.startswith(base.path):
        return None
    relative = path[len(base.path) :] or "index.html"
    if "\\" in relative or ".." in PurePosixPath(relative).parts:
        return None
    return relative


# Android 화면을 바꾸는 작업은 화면 전용 스레드에서 실행합니다.
class Task(dynamic_proxy(Runnable)):
    def __init__(self, function):
        super().__init__()
        self.function = function

    def run(self):
        self.function()


# HTML과 Python은 GitHub에서 함께 읽고, 인터넷이 없으면 APK 사본을 씁니다.
class Client(static_proxy(WebViewClient)):
    @constructor([])
    def __init__(self):
        super().__init__()
        self.owner = None
        self.screen = None
        self.screen_source = "offline"
        self.screen_lock = threading.Lock()

    # 화면과 코드의 SHA256을 비교해 서로 다른 버전이 섞이지 않게 합니다.
    def load_screen(self):
        with self.screen_lock:
            if self.screen is not None:
                return
            self.screen = {}
            try:
                with urlopen(SITE + "index.html", timeout=2) as source:
                    html = source.read(1_000_000)
                text = html.decode("utf-8")
                if '<meta name="netrobot-ui-version" content="3">' not in text:
                    raise ValueError("다른 화면 버전")
                expected = re.search(
                    r'name="netrobot-python-sha256" content="([0-9a-f]{64})"', text
                )
                with urlopen(SITE + "app.py", timeout=2) as source:
                    code = source.read(1_000_000)
                if expected is None or hashlib.sha256(code).hexdigest() != expected.group(1):
                    raise ValueError("화면과 Python 버전 불일치")
                self.screen = {"index.html": html, "app.py": code}
                self.screen_source = "github"
            except Exception:
                # 인터넷 없는 드론 Wi-Fi에서도 같은 기능을 실행합니다.
                self.screen_source = "offline"

    @Override(WebResourceResponse, [WebView, WebResourceRequest])
    def shouldInterceptRequest(self, view, request):
        try:
            url = str(request.getUrl())
            path = site_path(url)
            if path is None:
                return self.response(b"Blocked external request", "text/plain", 403)
            if str(request.getMethod()) != "GET":
                return self.response(b"GET only", "text/plain", 405)
            if path.startswith("native/"):
                return self.native("/" + path, parse_qs(urlsplit(url).query))
            mime = {
                ".py": "text/plain",
                ".js": "text/javascript",
                ".mjs": "text/javascript",
                ".wasm": "application/wasm",
                ".html": "text/html",
                ".svg": "image/svg+xml",
                ".json": "application/json",
            }.get(PurePosixPath(path).suffix, "application/octet-stream")
            try:
                if path in ("index.html", "app.py"):
                    self.load_screen()
                    if path in self.screen:
                        return self.response(self.screen[path], mime)
                # 외부 실행 라이브러리와 모델은 APK에 넣어 항상 로컬에서 읽습니다.
                stream = self.owner.getAssets().open("web/" + path)
                return WebResourceResponse(
                    mime,
                    (
                        "UTF-8"
                        if mime.startswith(("text/", "application/json", "image/svg"))
                        else None
                    ),
                    stream,
                )
            except Exception:
                return self.response(b"Not found", "text/plain", 404)
        except Exception as exc:
            return self.response(json.dumps({"error": str(exc)}).encode(), "application/json", 500)

    @Override(jboolean, [WebView, WebResourceRequest])
    def shouldOverrideUrlLoading(self, view, request):
        return site_path(str(request.getUrl())) is None

    # Python 데이터와 오류를 브라우저가 읽을 수 있는 응답으로 만듭니다.
    def response(self, data, mime="application/json", status=200, headers=None):
        stream = ByteArrayInputStream(jarray(jbyte)(data))
        response = WebResourceResponse(
            mime, "UTF-8" if mime.startswith(("text/", "application/json")) else None, stream
        )
        if status != 200:
            response.setStatusCodeAndReasonPhrase(status, "Error")
        response_headers = HashMap()
        for key, value in {"Cache-Control": "no-store", **(headers or {})}.items():
            response_headers.put(key, value)
        response.setResponseHeaders(response_headers)
        return response

    # 화면의 요청을 드론 수신부와 Wi-Fi 설정 화면에 전달합니다.
    def native(self, path, query):
        receiver = self.owner.receiver
        if path == "/native/connect":
            host = query.get("host", ["192.168.169.1"])[0]
            mode = query.get("mode", ["zigzag"])[0]
            self.owner.bind_wifi()
            receiver.connect(host, mode)
            return self.response(json.dumps({"ok": True, "simulated": True, "host": host}).encode())
        if path == "/native/disconnect":
            receiver.close()
            return self.response(b'{"ok":true}')
        if path == "/native/wifi":
            self.owner.runOnUiThread(
                Task(lambda: self.owner.startActivity(Intent(Settings.ACTION_WIFI_SETTINGS)))
            )
            return self.response(b'{"ok":true}')
        if path == "/native/status":
            import time

            with receiver.lock:
                ready = receiver.jpeg is not None and time.monotonic() - receiver.timestamp < 1.5
                data = {
                    "ready": ready,
                    "error": receiver.error,
                    "sequence": receiver.sequence,
                    "port": receiver.port,
                    "simulated": True,
                    "site_source": self.screen_source,
                }
            return self.response(json.dumps(data, ensure_ascii=False).encode())
        if path == "/native/frame.jpg":
            frame, sequence = receiver.frame()
            if frame is None:
                return self.response(b'{"error":"No drone frame yet"}', status=503)
            return self.response(frame, "image/jpeg", headers={"X-Frame-Sequence": str(sequence)})
        return self.response(b"Not found", "text/plain", 404)


# ONNX 선택 버튼은 Android의 기본 파일 선택창을 엽니다.
class Chrome(static_proxy(WebChromeClient)):
    @constructor([])
    def __init__(self):
        super().__init__()
        self.owner = None

    @Override(jboolean, [WebView, ValueCallback, WebChromeClient.FileChooserParams])
    def onShowFileChooser(self, view, callback, params):
        if self.owner.file_callback is not None:
            self.owner.file_callback.onReceiveValue(None)
        self.owner.file_callback = callback
        intent = Intent(Intent.ACTION_OPEN_DOCUMENT)
        intent.addCategory(Intent.CATEGORY_OPENABLE)
        intent.setType("*/*")
        self.owner.startActivityForResult(intent, 7337)
        return True


# 앱이 시작될 때 Python 영상 수신부와 웹 화면을 만듭니다.
class MainActivity(static_proxy(Activity)):
    @Override(jvoid, [Bundle])
    def onCreate(self, bundle):
        Activity.onCreate(self, bundle)
        self.file_callback = None
        self.getWindow().addFlags(
            WindowManager.LayoutParams.FLAG_FULLSCREEN
            | WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON
        )
        self.getWindow().getDecorView().setSystemUiVisibility(5894)
        self.jpeg_headers = json.loads(self.read_asset("jpeg_headers.json"))
        self.receiver = Receiver(self.load_header)
        self.web = WebView(self)
        self.client = Client()
        self.client.owner = self
        self.chrome = Chrome()
        self.chrome.owner = self
        self.web.setWebViewClient(self.client)
        self.web.setWebChromeClient(self.chrome)
        settings = self.web.getSettings()
        settings.setJavaScriptEnabled(True)
        settings.setDomStorageEnabled(True)
        settings.setCacheMode(WebSettings.LOAD_NO_CACHE)
        self.web.clearCache(True)  # 업데이트 후에도 새 화면과 모델 정보를 읽습니다.
        settings.setAllowFileAccess(False)
        settings.setAllowContentAccess(True)  # 기본 파일 선택창으로 선택한 모델을 읽습니다.
        settings.setMediaPlaybackRequiresUserGesture(False)
        settings.setSupportZoom(False)
        self.setContentView(self.web)
        self.web.loadUrl(SITE + "?app=1")

    # JPEG 사진 헤더는 APK에 저장된 작은 파일을 읽어 사용합니다.
    def load_header(self, quality):
        return b64decode(self.jpeg_headers[str(quality)])

    # APK 안의 파일을 바이트로 읽는 공통 함수입니다.
    def read_asset(self, path):
        source = self.getAssets().open(path)
        buffer = jarray(jbyte)(1024)
        result = bytearray()
        try:
            while True:
                count = source.read(buffer)
                if count < 0:
                    break
                result.extend(bytes(buffer)[:count])
        finally:
            source.close()
        return bytes(result)

    # 모바일 데이터가 켜져 있어도 드론 통신은 현재 Wi-Fi로 보냅니다.
    def bind_wifi(self):
        manager = self.getSystemService(Context.CONNECTIVITY_SERVICE)
        for network in manager.getAllNetworks():
            capabilities = manager.getNetworkCapabilities(network)
            if capabilities is not None and capabilities.hasTransport(
                NetworkCapabilities.TRANSPORT_WIFI
            ):
                manager.bindProcessToNetwork(network)
                return
        raise RuntimeError("먼저 휴대폰을 FLOW_27AF9C Wi-Fi에 연결하세요.")

    # 사용자가 고른 모델 파일 주소를 웹 화면에 돌려줍니다.
    @Override(jvoid, [jint, jint, Intent])
    def onActivityResult(self, request_code, result_code, data):
        Activity.onActivityResult(self, request_code, result_code, data)
        if request_code == 7337 and self.file_callback is not None:
            result = (
                jarray(Uri)([data.getData()])
                if result_code == Activity.RESULT_OK and data is not None
                else None
            )
            self.file_callback.onReceiveValue(result)
            self.file_callback = None

    # 앱이 뒤로 가면 영상 수신과 조종 상태를 정지합니다.
    @Override(jvoid, [])
    def onPause(self):
        if hasattr(self, "receiver"):
            self.receiver.close()
        if hasattr(self, "web"):
            self.web.evaluateJavascript("window.netrobotPause?.()", None)
            self.web.onPause()
        Activity.onPause(self)

    # 다시 돌아오면 웹 화면을 깨우고 영상 연결을 재개합니다.
    @Override(jvoid, [])
    def onResume(self):
        Activity.onResume(self)
        if hasattr(self, "web"):
            self.web.onResume()
            self.web.evaluateJavascript("window.netrobotResume?.()", None)

    # 앱을 닫을 때 통신과 화면 자원을 해제합니다.
    @Override(jvoid, [])
    def onDestroy(self):
        if hasattr(self, "receiver"):
            self.receiver.close()
        if hasattr(self, "web"):
            self.web.destroy()
        Activity.onDestroy(self)
