"""화면과 조종, 그물 감지를 한곳에 모은 Python 코드입니다.

브라우저에서는 Brython이 실행합니다. 아래의 기본 계산 함수는 일반
Python에서도 그대로 실행할 수 있으므로 자동 검사에도 함께 사용합니다.
"""

import math
import sys


# 조이스틱 중심에서 얼마나 움직였는지 -1~1 범위로 계산합니다.
def joystick_vector(dx, dy, radius, deadzone=0.12):
    distance = math.hypot(dx, dy)
    if radius <= 0 or distance / radius < deadzone:
        return 0.0, 0.0
    power = min(1.0, distance / radius)
    return dx / distance * power, -dy / distance * power


# 왼쪽 두 바퀴와 오른쪽 두 바퀴의 회전 방향을 계산합니다.
def wheel_values(x, y, speed=1.0):
    if not all(math.isfinite(v) for v in (x, y, speed)):
        raise ValueError("입력값은 유한한 숫자여야 합니다.")
    if abs(x) > 1 or abs(y) > 1 or not 0 <= speed <= 1:
        raise ValueError("조종값의 범위를 확인하세요.")
    left, right = y + x, y - x
    maximum = max(1, abs(left), abs(right))
    return [left / maximum * speed] * 2 + [right / maximum * speed] * 2


# 화면에 표시할 이동 방향 이름을 정합니다.
def direction_name(x, y):
    if math.hypot(x, y) < 0.01:
        return "정지"
    if abs(y) >= abs(x):
        return "전진" if y > 0 else "후진"
    return "우회전" if x > 0 else "좌회전"


# 두 사각형이 얼마나 겹치는지 0~1 값으로 계산합니다.
def box_iou(a, b):
    width = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    height = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    overlap = width * height
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return overlap / max(1e-9, area_a + area_b - overlap)


# YOLO의 숫자 출력을 원본 영상의 그물 박스로 바꿉니다.
def decode_yolo(data, dimensions, width, height, threshold=0.4, size=640):
    if width <= 0 or height <= 0:
        raise ValueError("영상 크기가 올바르지 않습니다.")
    if list(dimensions) != [1, 5, (size // 8) ** 2 + (size // 16) ** 2 + (size // 32) ** 2]:
        raise ValueError("그물 한 종류를 학습한 640 입력 YOLOv8 모델이 필요합니다.")
    count = dimensions[2]
    scale = min(size / width, size / height)
    new_width = math.floor(width * scale + 0.5)
    new_height = math.floor(height * scale + 0.5)
    left, top = (size - new_width) // 2, (size - new_height) // 2

    # 점수가 낮은 후보는 버리고, 남은 좌표에서 회색 여백을 제거합니다.
    candidates = []
    for i in range(count):
        score = float(data[4 * count + i])
        if not math.isfinite(score) or score < threshold:
            continue
        cx, cy, bw, bh = [float(data[c * count + i]) for c in range(4)]
        if not all(math.isfinite(v) for v in (cx, cy, bw, bh)):
            continue
        box = [
            max(0, (cx - bw / 2 - left) / scale),
            max(0, (cy - bh / 2 - top) / scale),
            min(width, (cx + bw / 2 - left) / scale),
            min(height, (cy + bh / 2 - top) / scale),
        ]
        if all(math.isfinite(v) for v in box) and box[2] > box[0] and box[3] > box[1]:
            candidates.append({"box": box, "score": score, "name": "그물"})

    # 같은 그물 주변의 겹치는 박스는 점수가 높은 것만 남깁니다.
    candidates.sort(key=lambda item: item["score"], reverse=True)
    result = []
    for candidate in candidates:
        if not any(box_iou(candidate["box"], old["box"]) > 0.45 for old in result):
            result.append(candidate)
        if len(result) == 40:
            break
    return result


# 아래 부분은 브라우저에서만 실행합니다. 위 계산 함수는 PC 검사에도 씁니다.
if sys.platform == "brython":
    import json
    import javascript
    from browser import document, window, timer, aio

    # 영상 상태와 조종 상태를 한 사전에 모아 파일 사이 전달을 줄였습니다.
    state = {
        "source": "none",
        "generation": 0,
        "frame_time": 0,
        "sequence": None,
        "width": 0,
        "height": 0,
        "frames": 0,
        "fps_time": 0,
        "x": 0.0,
        "y": 0.0,
        "grip": "stop",
        "paused": False,
        "pointer": None,
        "grip_pointer": None,
        "keys": set(),
        "model": None,
        "loading": False,
        "detecting": False,
        "detections": [],
        "enabled": window.localStorage.getItem("netrobot-detection") != "off",
        "threshold": 0.4,
        "inference_ms": 0,
        "robot_visible": True,
        "openness": 0.5,
        "angles": [0.0] * 5,
        "last_animation": 0,
        "toast_timer": None,
        "media_image": None,
        "media_url": None,
    }
    native = window.URLSearchParams.new(window.location.search).get("app") == "1"
    local_bridge = window.URLSearchParams.new(window.location.search).get("bridge") == "1"
    receiver_available = native or local_bridge
    if receiver_available:
        document["localControl"].hidden = True
        document["connectionGuide"].text = (
            "인터넷 없이 실행 중입니다. 드론 Wi-Fi에 연결하면 영상을 자동으로 기다립니다."
        )
    if native:
        document.body.classList.add("native-app")

    # 자주 쓰는 화면 요소와 현재 시각을 짧은 이름으로 가져옵니다.
    def el(name):
        return document[name]

    def now():
        return window.performance.now()

    # JavaScript 라이브러리의 비동기 결과를 Python에서 기다립니다.
    async def wait(promise):
        future = aio.Future()
        promise.then(
            lambda value: future.set_result(value),
            lambda error: future.set_exception(RuntimeError(str(error))),
        )
        return await future

    # 짧은 알림은 몇 초 뒤 자동으로 감춥니다.
    def toast(message):
        el("toast").text = str(message)
        el("toast").hidden = False
        if state["toast_timer"] is not None:
            timer.clear_timeout(state["toast_timer"])
        state["toast_timer"] = timer.set_timeout(lambda: setattr(el("toast"), "hidden", True), 4500)

    # Python 수신부의 기능은 같은 사이트의 native 경로로 요청합니다.
    async def request(path, query=None):
        url = window.URL.new("native/" + path, window.location.href)
        for key, value in (query or {}).items():
            url.searchParams.set(key, str(value))
        response = await wait(
            window.fetch(
                url.href, {"cache": "no-store", "signal": window.AbortSignal.timeout(2500)}
            )
        )
        if not response.ok:
            message = await wait(response.text())
            try:
                message = json.loads(message).get("error", message)
            except ValueError:
                pass
            raise RuntimeError(message)
        return response

    # 연결 상태와 감지 상태를 화면에 표시합니다.
    def camera_status(message, connected=False):
        el("connectionState").lastElementChild.textContent = message
        el("connectionState").classList.toggle("live", connected)

    def vision_status():
        if not state["enabled"]:
            title, detail = "그물 감지 꺼짐", "설정에서 감지를 켤 수 있습니다"
        elif state["source"] == "demo":
            title, detail = "조종 연습", "가상 화면 · 실제 감지 아님"
        elif state["loading"]:
            title, detail = "모델 준비 중", "이 기기에서 모델을 불러옵니다"
        elif state["model"] is None:
            title, detail = "그물 감지 준비", "시험용 그물 모델을 불러오세요"
        else:
            count = len(state["detections"])
            title = (
                "그물 모델 준비됨"
                if state["source"] == "none"
                else (f"그물 {count}개 감지" if count else "그물 탐색 중")
            )
            detail = f"기기 내 추론 · {round(state['inference_ms'])}ms · 시험용 모델"
        el("visionState").text = title
        el("modelState").text = detail
        el("netCount").text = "예시" if state["source"] == "demo" else str(len(state["detections"]))

    # 조종은 아직 실제 모터 대신 화면의 로봇에 적용합니다.
    def render_controls():
        x, y = state["x"], state["y"]
        el("directionState").text = direction_name(x, y)
        el("powerValue").text = str(0 if state["paused"] else round(min(1, math.hypot(x, y)) * 50))
        el("gripperState").text = {"open": "열림 동작", "close": "닫힘 동작", "stop": "대기"}[
            state["grip"]
        ]
        el("gripperOpen").classList.toggle("active", state["grip"] == "open")
        el("gripperClose").classList.toggle("active", state["grip"] == "close")
        el("joystick").setAttribute("aria-valuenow", el("powerValue").text)
        el("joystick").setAttribute("aria-valuetext", direction_name(x, y))

    # 손을 놓거나 앱을 벗어나면 가상 주행과 집게를 정지합니다.
    def stop_drive(event=None):
        state["x"], state["y"], state["pointer"] = 0.0, 0.0, None
        state["keys"].clear()
        el("joystickKnob").style.transform = "translate(0,0)"
        el("joystick").classList.remove("dragging")
        render_controls()

    def stop_grip(event=None):
        state["grip"], state["grip_pointer"] = "stop", None
        render_controls()

    def stop_all(event=None):
        stop_drive()
        stop_grip()

    # 터치 위치를 읽어 조이스틱 손잡이와 이동값을 갱신합니다.
    def move_joystick(event):
        if state["pointer"] != event.pointerId:
            return
        rect = el("joystick").getBoundingClientRect()
        radius = rect.width * 0.34
        state["x"], state["y"] = joystick_vector(
            event.clientX - rect.left - rect.width / 2,
            event.clientY - rect.top - rect.height / 2,
            radius,
        )
        el("joystickKnob").style.transform = (
            f"translate({state['x']*radius}px,{-state['y']*radius}px)"
        )
        render_controls()

    def start_joystick(event):
        if state["paused"] or state["pointer"] is not None:
            return
        event.preventDefault()
        state["pointer"] = event.pointerId
        el("joystick").setPointerCapture(event.pointerId)
        el("joystick").classList.add("dragging")
        move_joystick(event)

    # 집게 버튼 두 개에 같은 처리 함수를 연결합니다.
    def bind_gripper(name, action):
        button = el(name)

        def start(event):
            if not state["paused"]:
                state["grip"] = action
                if event.type == "pointerdown":
                    button.setPointerCapture(event.pointerId)
                render_controls()

        # 터치의 click은 pointerup 뒤에 발생하므로 다시 시작하지 않습니다.
        def click(event):
            if event.detail == 0:
                start(event)
                timer.set_timeout(stop_grip, 250)

        button.bind("click", click)
        button.bind("pointerdown", start)
        button.bind("pointerup", stop_grip)
        button.bind("pointercancel", stop_grip)
        button.bind("lostpointercapture", stop_grip)

    # 키보드 화살표와 WASD도 조이스틱과 같은 값으로 바꿉니다.
    key_vectors = {
        "ArrowUp": (0, 1),
        "w": (0, 1),
        "ArrowDown": (0, -1),
        "s": (0, -1),
        "ArrowLeft": (-1, 0),
        "a": (-1, 0),
        "ArrowRight": (1, 0),
        "d": (1, 0),
    }

    def keyboard(event):
        if el("settingsDialog").open or event.target.tagName in ("INPUT", "TEXTAREA"):
            return
        key = event.key.lower() if len(event.key) == 1 else event.key
        if key not in key_vectors:
            return
        event.preventDefault()
        if event.type == "keydown" and not state["paused"]:
            state["keys"].add(key)
        else:
            state["keys"].discard(key)
        x = sum(key_vectors[k][0] for k in state["keys"])
        y = sum(key_vectors[k][1] for k in state["keys"])
        length = max(1, math.hypot(x, y))
        state["x"], state["y"] = x / length, y / length
        render_controls()

    # 로봇 그림의 바퀴·기어·집게를 조종값에 맞춰 움직입니다.
    def animate_robot(timestamp):
        dt = (
            min(0.08, (timestamp - state["last_animation"]) / 1000)
            if state["last_animation"]
            else 0
        )
        state["last_animation"] = timestamp
        values = wheel_values(
            0 if state["paused"] else state["x"], 0 if state["paused"] else state["y"]
        )
        grip = 0 if state["paused"] else {"open": 1, "close": -1, "stop": 0}[state["grip"]]
        if (state["openness"] >= 1 and grip > 0) or (state["openness"] <= 0 and grip < 0):
            grip = 0
            stop_grip()
        state["openness"] = max(0, min(1, state["openness"] + grip * dt * 0.6))
        for i, value in enumerate(values + [grip]):
            motor = el("motor" + str(i))
            motor.classList.toggle("motor-forward", value > 0.01)
            motor.classList.toggle("motor-reverse", value < -0.01)
            motor.setAttribute("data-running", "true" if abs(value) > 0.01 else "false")
            state["angles"][i] = (state["angles"][i] + value * dt * 240) % 360
            motor.querySelector(".motor-gear").setAttribute(
                "transform", f"rotate({state['angles'][i]})"
            )
        angle = 16 - state["openness"] * 40
        el("clawLeft").setAttribute("transform", f"rotate({angle} 181 104)")
        el("clawRight").setAttribute("transform", f"rotate({-angle} 219 104)")
        el("gripPosition").text = f"집게 {round(state['openness']*100)}% 열림"
        el("robotMotion").text = (
            "긴급 정지"
            if state["paused"]
            else ("집게 동작" if grip else direction_name(state["x"], state["y"]))
        )

    # 외부 JavaScript 라이브러리만 불러오며, 기능 코드는 Python에 둡니다.
    async def load_library(suffix=""):
        loaded = {}
        url = window.URL.new("vendor/ort.wasm.min.mjs" + suffix, window.location.href).href
        javascript.import_modules([url], lambda module: loaded.update(module=module))
        for _ in range(300):
            if "module" in loaded:
                return loaded["module"]
            await aio.sleep(0.1)
        raise RuntimeError("추론 라이브러리를 불러오지 못했습니다.")

    # 이미지 변환과 신경망 계산은 검증된 외부 라이브러리를 호출합니다.
    class Detector:
        def __init__(self, library, session):
            self.library, self.session = library, session
            self.canvas = document.createElement("canvas")
            # Brython의 .width는 CSS 크기이므로 실제 픽셀 수는 HTML 속성에 씁니다.
            self.canvas.attrs["width"] = 640
            self.canvas.attrs["height"] = 640
            self.context = self.canvas.getContext("2d", {"willReadFrequently": True})

        async def predict(self, source, width, height, threshold):
            scale = min(640 / width, 640 / height)
            nw, nh = math.floor(width * scale + 0.5), math.floor(height * scale + 0.5)
            self.context.fillStyle = "rgb(114,114,114)"
            self.context.fillRect(0, 0, 640, 640)
            self.context.drawImage(source, (640 - nw) // 2, (640 - nh) // 2, nw, nh)
            image = self.context.getImageData(0, 0, 640, 640)
            tensor = await wait(
                self.library.Tensor.fromImage(
                    image,
                    {
                        "tensorFormat": "RGB",
                        "tensorLayout": "NCHW",
                        "dataType": "float32",
                        "norm": {"mean": [255, 255, 255], "bias": [0, 0, 0]},
                    },
                )
            )
            outputs = None
            try:
                feeds = window.Object.new()
                feeds[self.session.inputNames[0]] = tensor
                outputs = await wait(self.session.run(feeds))
                output = outputs[self.session.outputNames[0]]
                return decode_yolo(output.data, output.dims, width, height, threshold)
            finally:
                tensor.dispose()
                if outputs is not None:
                    for name in self.session.outputNames:
                        outputs[name].dispose()

    # 모델을 처음 실행해 입력·출력 형식을 확인한 뒤 기존 모델과 교체합니다.
    async def load_model(data, name):
        if state["loading"]:
            return False
        state["loading"] = True
        vision_status()
        try:
            library = await load_library("?v=1.20.1")
            library.env.wasm.numThreads = 1
            library.env.wasm.proxy = hasattr(window, "Worker")
            library.env.wasm.wasmPaths = window.URL.new("vendor/", window.location.href).href
            try:
                session = await wait(
                    library.InferenceSession.create(data.slice(0), {"executionProviders": ["wasm"]})
                )
            except Exception:
                library = await load_library("?main=1")
                library.env.wasm.numThreads = 1
                library.env.wasm.proxy = False
                library.env.wasm.wasmPaths = window.URL.new("vendor/", window.location.href).href
                session = await wait(
                    library.InferenceSession.create(data.slice(0), {"executionProviders": ["wasm"]})
                )
            candidate = Detector(library, session)
            await candidate.predict(candidate.canvas, 640, 640, 0.4)
            while state["detecting"]:
                await aio.sleep(0.03)
            old = state["model"]
            state["model"] = candidate
            if old is not None:
                await wait(old.session.release())
            toast("그물 모델 연결됨: " + name)
            return True
        except Exception as error:
            el("connectionError").text = str(error)
            toast("모델 불러오기 실패: " + str(error))
            return False
        finally:
            state["loading"] = False
            vision_status()

    # 선택한 모델은 IndexedDB에 저장하므로 다음 실행에도 기기에 남습니다.
    async def model_database():
        request_db = window.indexedDB.open("netrobot-offline", 1)
        request_db.onupgradeneeded = lambda event: event.target.result.createObjectStore("models")
        future = aio.Future()
        request_db.onsuccess = lambda event: future.set_result(event.target.result)
        request_db.onerror = lambda event: future.set_exception(RuntimeError("모델 저장소 오류"))
        return await future

    async def saved_model(data=None, name=None):
        db = await model_database()
        future = aio.Future()
        transaction = db.transaction("models", "readonly" if data is None else "readwrite")
        store = transaction.objectStore("models")
        if data is None:
            req = store.get("net")
            req.onsuccess = lambda event: future.set_result(event.target.result)
            req.onerror = lambda event: future.set_exception(RuntimeError("저장 모델 읽기 실패"))
        else:
            value = window.Object.new()
            value.bytes, value.name = data, name
            store.put(value, "net")
            transaction.oncomplete = lambda event: future.set_result(None)
            transaction.onerror = lambda event: future.set_exception(RuntimeError("모델 저장 실패"))
        try:
            return await future
        finally:
            db.close()

    # 사용자 모델이 없으면 사이트의 기본 그물 모델을 자동으로 불러옵니다.
    async def restore_model():
        try:
            saved = await saved_model()
            if saved and await load_model(saved.bytes, saved.name):
                return
        except Exception:
            pass
        try:
            response = await wait(window.fetch("models/model.json"))
            info = json.loads(await wait(response.text()))
            if info.get("available") and info.get("trained_on_net"):
                response = await wait(window.fetch("models/" + info["file"]))
                data = await wait(response.arrayBuffer())
                if await load_model(data, "기본 시험용 모델"):
                    await saved_model(data, "기본 시험용 모델")
        except Exception as error:
            toast("기본 모델 확인: " + str(error))

    async def choose_model(event):
        if event.target.files.length:
            file = event.target.files[0]
            data = await wait(file.arrayBuffer())
            if await load_model(data, file.name):
                await saved_model(data, file.name)

    # 앱에 영상 수신을 요청하고, 새 영상만 화면에 갱신합니다.
    def release_video():
        state["generation"] += 1
        state["source"], state["frame_time"], state["sequence"] = "none", 0, None
        state["detections"] = []
        el("welcome").hidden = False
        el("remoteFrame").hidden = el("demoFrame").hidden = True
        el("fileVideo").pause()
        el("fileVideo").removeAttribute("src")
        if state["media_image"] is not None:
            state["media_image"].close()
            state["media_image"] = None
        if state["media_url"] is not None:
            window.URL.revokeObjectURL(state["media_url"])
            state["media_url"] = None
        stop_all()

    # 입력 방식에 맞는 설정만 보여 줍니다.
    def source_changed(event=None):
        mode = el("sourceMode").value
        el("fileSourceFields").hidden = mode != "file"
        el("snapshotSourceFields").hidden = mode != "snapshot"
        el("flowSourceFields").hidden = mode != "flow"
        el("pairButton").hidden = mode == "file"
        el("droneWifiButton").hidden = not native
        el("connectionError").text = ""

    # 읽어 온 사진이나 영상의 실제 픽셀을 같은 카메라 캔버스에 표시합니다.
    def show_frame(source, width, height):
        canvas = el("remoteFrame")
        if canvas.getAttribute("width") != str(width):
            canvas.attrs["width"] = width
        if canvas.getAttribute("height") != str(height):
            canvas.attrs["height"] = height
        canvas.getContext("2d").drawImage(source, 0, 0)
        state.update(width=width, height=height, frame_time=now(), frames=state["frames"] + 1)
        el("welcome").hidden = el("previewBadge").hidden = True
        canvas.hidden = False

    # 사진과 영상 파일은 업로드하지 않고 현재 브라우저에서만 엽니다.
    async def choose_media(event):
        if not event.target.files.length:
            return
        file = event.target.files[0]
        release_video()
        generation = state["generation"]
        try:
            if file.type.startswith("image/"):
                image = await wait(window.createImageBitmap(file))
                if generation != state["generation"]:
                    image.close()
                    return
                state["media_image"] = image
            elif file.type.startswith("video/"):
                state["media_url"] = window.URL.createObjectURL(file)
                video = el("fileVideo")
                video.src = state["media_url"]
                await wait(video.play())
            else:
                raise ValueError("사진 또는 브라우저가 재생할 수 있는 영상 파일을 선택하세요.")
            if generation != state["generation"]:
                return
            state["source"] = "media"
            el("settingsDialog").close()
            camera_status("파일 감지 · " + file.name, True)
            aio.run(media_loop(generation))
        except Exception as error:
            el("connectionError").text = str(error)
            toast("파일 열기 실패: " + str(error))

    # 파일 프레임을 0.1초마다 갱신해 실제 모델의 입력으로 사용합니다.
    async def media_loop(generation):
        while state["source"] == "media" and generation == state["generation"]:
            image = state["media_image"]
            video = el("fileVideo")
            if image is not None:
                show_frame(image, image.width, image.height)
            elif video.readyState >= 2:
                show_frame(video, video.videoWidth, video.videoHeight)
            await aio.sleep(0.1)

    # 웹에서 읽을 수 있는 JPEG 카메라 주소를 반복해서 가져옵니다.
    async def snapshot_loop(url, generation):
        while state["source"] == "snapshot" and generation == state["generation"]:
            try:
                response = await wait(
                    window.fetch(
                        url, {"cache": "no-store", "signal": window.AbortSignal.timeout(5000)}
                    )
                )
                if not response.ok:
                    raise RuntimeError("카메라 응답: " + str(response.status))
                image = await wait(window.createImageBitmap(await wait(response.blob())))
                if generation == state["generation"]:
                    show_frame(image, image.width, image.height)
                    camera_status("JPEG 카메라 연결됨", True)
                image.close()
            except Exception:
                state["detections"] = []
                camera_status("카메라 주소·HTTPS·CORS 설정을 확인하세요")
            await aio.sleep(0.1)

    async def connect(event=None):
        if event is not None:
            event.preventDefault()
        mode = el("sourceMode").value
        if mode == "file":
            toast("설정에서 사진·영상 파일을 선택하세요.")
            return
        if mode == "snapshot":
            try:
                url = window.URL.new(el("snapshotUrl").value.strip(), window.location.href)
            except Exception:
                el("connectionError").text = "올바른 JPEG 주소를 입력하세요."
                return
            if url.protocol not in ("http:", "https:") or not el("snapshotUrl").value.strip():
                el("connectionError").text = "HTTP 또는 HTTPS JPEG 주소를 입력하세요."
                return
            release_video()
            state["source"] = "snapshot"
            el("settingsDialog").close()
            aio.run(snapshot_loop(url.href, state["generation"]))
            return
        if not receiver_available:
            el("connectionError").text = (
                "FLOW UDP 영상에는 Python 수신부가 필요합니다. 수신부가 출력한 브라우저 조종 주소를 여세요."
            )
            return
        try:
            release_video()
            await request(
                "connect", {"host": el("droneAddress").value.strip(), "mode": el("jpegMode").value}
            )
            window.localStorage.setItem("netrobot-drone", el("droneAddress").value.strip())
            window.localStorage.setItem("netrobot-jpeg-mode", el("jpegMode").value)
            state["source"] = "native"
            el("welcome").hidden = el("previewBadge").hidden = True
            el("remoteFrame").hidden = False
            el("settingsDialog").close()
            aio.run(video_loop(state["generation"]))
        except Exception as error:
            el("connectionError").text = str(error)
            toast(error)

    async def video_loop(generation):
        while state["source"] == "native" and generation == state["generation"]:
            try:
                response = await request("status")
                status = json.loads(await wait(response.text()))
                if not status["ready"]:
                    camera_status(status["error"] or "영상 수신 대기")
                    await aio.sleep(0.3)
                    continue
                if status["sequence"] == state["sequence"]:
                    await aio.sleep(0.04)
                    continue
                response = await request("frame.jpg")
                image = await wait(window.createImageBitmap(await wait(response.blob())))
                if generation != state["generation"]:
                    image.close()
                    return
                canvas = el("remoteFrame")
                canvas.attrs["width"] = image.width
                canvas.attrs["height"] = image.height
                canvas.getContext("2d").drawImage(image, 0, 0)
                image.close()
                state.update(
                    width=int(canvas.getAttribute("width")),
                    height=int(canvas.getAttribute("height")),
                    frame_time=now(),
                    sequence=status["sequence"],
                    frames=state["frames"] + 1,
                )
                camera_status("드론 영상 연결됨", True)
                el("siteSource").text = "영상: Python 수신부 · 감지와 조종: 현재 브라우저"
            except Exception as error:
                camera_status("영상 수신 대기 · Wi-Fi 확인")
            await aio.sleep(0.07)

    # 추론을 겹쳐 실행하지 않고, 완료한 결과만 화면에 전달합니다.
    async def detection_loop():
        while True:
            if (
                state["enabled"]
                and state["model"] is not None
                and not state["loading"]
                and state["source"] in ("native", "media", "snapshot")
                and now() - state["frame_time"] < 1000
                and not document.hidden
            ):
                state["detecting"] = True
                generation = state["generation"]
                try:
                    start = now()
                    boxes = await state["model"].predict(
                        el("remoteFrame"), state["width"], state["height"], state["threshold"]
                    )
                    if generation == state["generation"] and state["enabled"]:
                        state["detections"] = boxes
                        state["inference_ms"] = now() - start
                        vision_status()
                except Exception as error:
                    state["enabled"] = False
                    el("detectionToggle").checked = False
                    toast("감지 중지: " + str(error))
                finally:
                    state["detecting"] = False
            await aio.sleep(0.1)

    # 연습 화면은 가상 그림이라는 표시를 유지하며 실제 감지와 구분합니다.
    def practice_frame():
        canvas = el("demoFrame")
        if canvas.getAttribute("width") != "1280":
            canvas.attrs["width"] = 1280
            canvas.attrs["height"] = 720
        ctx = canvas.getContext("2d")
        ctx.fillStyle = "#48545c"
        ctx.fillRect(0, 0, 1280, 720)
        ctx.strokeStyle = "#a0b099"
        for x in range(420, 870, 24):
            ctx.beginPath()
            ctx.moveTo(x, 200)
            ctx.lineTo(x + 65, 510)
            ctx.moveTo(x, 510)
            ctx.lineTo(x + 65, 200)
            ctx.stroke()
        state.update(width=1280, height=720, frame_time=now(), frames=state["frames"] + 1)
        state["detections"] = [
            {"box": [400, 190, 900, 520], "score": None, "name": "그물 표시 예시"}
        ]

    def submit_connection(event):
        event.preventDefault()
        aio.run(connect())

    # 연습 모드에서는 실제 카메라 대신 표시용 그림을 사용합니다.
    def start_demo(event=None):
        release_video()
        if receiver_available:
            aio.run(request("disconnect"))
        state["source"] = "demo"
        state["paused"] = False
        el("welcome").hidden = True
        el("demoFrame").hidden = False
        el("previewBadge").hidden = False
        el("pausedBanner").hidden = True
        el("settingsDialog").close()
        camera_status("연습 모드", True)
        vision_status()

    # 감지 좌표를 화면 크기에 맞춰 그리고 박스 옆에 점수를 표시합니다.
    def draw_boxes():
        canvas = el("boxes")
        width, height = window.innerWidth, window.innerHeight
        dpr = min(window.devicePixelRatio or 1, 2)
        if canvas.getAttribute("width") != str(round(width * dpr)) or canvas.getAttribute(
            "height"
        ) != str(round(height * dpr)):
            canvas.attrs["width"] = round(width * dpr)
            canvas.attrs["height"] = round(height * dpr)
        ctx = canvas.getContext("2d")
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
        ctx.clearRect(0, 0, width, height)
        if not state["enabled"] or not state["width"] or now() - state["frame_time"] > 1200:
            return
        scale = min(width / state["width"], height / state["height"])
        left, top = (width - state["width"] * scale) / 2, (height - state["height"] * scale) / 2
        for item in state["detections"]:
            x1, y1, x2, y2 = item["box"]
            x, y = left + x1 * scale, top + y1 * scale
            ctx.strokeStyle = "#70ee99"
            ctx.lineWidth = 2
            ctx.strokeRect(x, y, (x2 - x1) * scale, (y2 - y1) * scale)
            text = item["name"] if item["score"] is None else f"그물 {round(item['score']*100)}%"
            ctx.font = "14px sans-serif"
            ctx.fillStyle = "#70ee99"
            ctx.fillRect(x, max(0, y - 24), ctx.measureText(text).width + 12, 24)
            ctx.fillStyle = "#111"
            ctx.fillText(text, x + 6, max(16, y - 7))

    # 화면 애니메이션은 영상 수신과 추론을 기다리지 않고 반복합니다.
    def animation(timestamp):
        animate_robot(timestamp)
        if state["source"] == "demo":
            practice_frame()
        draw_boxes()
        if timestamp - state["fps_time"] > 1000:
            el("frameRate").text = (
                str(round(state["frames"] * 1000 / max(1, timestamp - state["fps_time"]))) + " FPS"
            )
            el("frameSize").text = f"{state['width']} × {state['height']}"
            state["fps_time"], state["frames"] = timestamp, 0
        window.requestAnimationFrame(animation)

    # 설정 버튼과 표시 전환 버튼을 처리합니다.
    def open_settings(event=None):
        stop_all()
        el("settingsDialog").showModal()

    def toggle_robot(event):
        state["robot_visible"] = not state["robot_visible"]
        el("robotHologram").hidden = not state["robot_visible"]
        el("hologramToggle").setAttribute("aria-pressed", str(state["robot_visible"]).lower())
        el("hologramToggle").lastElementChild.textContent = (
            "로봇 모형 끄기" if state["robot_visible"] else "로봇 모형 켜기"
        )

    def toggle_detection(event):
        state["enabled"] = event.target.checked
        state["detections"] = []
        window.localStorage.setItem("netrobot-detection", "on" if state["enabled"] else "off")
        vision_status()

    def threshold_changed(event):
        state["threshold"] = float(event.target.value) / 100
        el("thresholdValue").text = event.target.value + "%"

    def emergency(event=None):
        state["paused"] = True
        stop_all()
        el("pausedBanner").hidden = False

    def resume_controls(event=None):
        state["paused"] = False
        el("pausedBanner").hidden = True
        stop_all()

    async def fullscreen(event=None):
        try:
            if document.fullscreenElement:
                await wait(document.exitFullscreen())
            else:
                await wait(el("cockpit").requestFullscreen())
        except Exception:
            toast("브라우저 메뉴의 전체 화면을 사용하세요.")

    # Android의 화면 숨김·복귀 알림에서도 같은 Python 함수를 사용합니다.
    def pause_app():
        release_video()

    def resume_app():
        if receiver_available and not el("settingsDialog").open and state["source"] == "none":
            aio.run(connect())

    window.netrobotPause, window.netrobotResume = pause_app, resume_app
    el("droneAddress").value = window.localStorage.getItem("netrobot-drone") or "192.168.169.1"
    el("jpegMode").value = window.localStorage.getItem("netrobot-jpeg-mode") or "zigzag"
    el("detectionToggle").checked = state["enabled"]
    el("sourceMode").value = "flow" if receiver_available else "file"
    source_changed()

    # 모든 버튼의 연결을 마지막에 모아 어디서 동작이 시작되는지 쉽게 봅니다.
    el("joystick").bind("pointerdown", start_joystick)
    el("joystick").bind("pointermove", move_joystick)
    for name in ("pointerup", "pointercancel", "lostpointercapture"):
        el("joystick").bind(name, stop_drive)
    bind_gripper("gripperOpen", "open")
    bind_gripper("gripperClose", "close")
    for name in ("keydown", "keyup"):
        document.bind(name, keyboard)
    window.bind("blur", stop_all)
    el("settingsDialog").bind("close", stop_all)
    el("settingsButton").bind("click", open_settings)
    el("connectLaptop").bind("click", open_settings)
    el("closeSettings").bind("click", lambda event: el("settingsDialog").close())
    el("cameraButton").bind(
        "click", lambda event: aio.run(connect()) if native else open_settings()
    )
    el("connectionForm").bind("submit", submit_connection)
    el("sourceMode").bind("change", source_changed)
    el("cameraFile").bind("change", lambda event: aio.run(choose_media(event)))
    for name in ("startDemo", "demoButton"):
        el(name).bind("click", start_demo)
    el("droneWifiButton").bind(
        "click",
        lambda event: (
            aio.run(request("wifi"))
            if native
            else toast("기기의 Wi-Fi 설정에서 드론에 연결하세요.")
        ),
    )
    el("hologramToggle").bind("click", toggle_robot)
    el("detectionToggle").bind("change", toggle_detection)
    el("threshold").bind("input", threshold_changed)
    el("modelFile").bind("change", lambda event: aio.run(choose_model(event)))
    el("stopButton").bind("click", emergency)
    el("resumeButton").bind("click", resume_controls)
    el("fullscreenButton").bind("click", lambda event: aio.run(fullscreen(event)))

    # 프로그램을 시작하면 모델 준비와 영상 연결을 각각 실행합니다.
    render_controls()
    vision_status()
    aio.run(restore_model())
    aio.run(detection_loop())
    window.requestAnimationFrame(animation)
    camera_status("웹 조종 · 영상 연결 전")
    if receiver_available:
        aio.run(connect())
