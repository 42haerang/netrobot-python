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


# 좌우 앞바퀴 두 개의 회전 방향을 계산합니다.
def wheel_values(x, y, speed=1.0):
    if not all(math.isfinite(v) for v in (x, y, speed)):
        raise ValueError("입력값은 유한한 숫자여야 합니다.")
    if abs(x) > 1 or abs(y) > 1 or not 0 <= speed <= 1:
        raise ValueError("조종값의 범위를 확인하세요.")
    left, right = y + x, y - x
    maximum = max(1, abs(left), abs(right))
    return [left / maximum * speed, right / maximum * speed]


# 화면에 표시할 이동 방향 이름을 정합니다.
def direction_name(x, y):
    if math.hypot(x, y) < 0.01:
        return "정지"
    if abs(y) >= abs(x):
        return "전진" if y > 0 else "후진"
    return "우회전" if x > 0 else "좌회전"


# 화면은 Python으로 조작하고, 영상 추론과 모터 통신은 노트북 Python에 요청합니다.
if sys.platform == "brython":
    import json
    from browser import document, window, aio, timer

    local = window.URLSearchParams.new(window.location.search).get("bridge") == "1"
    state = {
        "source": "none",
        "generation": 0,
        "x": 0.0,
        "y": 0.0,
        "grip": 0,
        "pointer": None,
        "keys": set(),
        "paused": False,
        "connected": False,
        "port": "",
        "armed": False,
        "speed": 0.35,
        "enabled": True,
        "threshold": 0.4,
        "model_ready": False,
        "vision_error": "",
        "count": 0,
        "ms": 0,
        "width": 0,
        "height": 0,
        "frames": 0,
        "fps_time": 0,
        "media_image": None,
        "media_url": None,
        "toast_timer": None,
    }

    # 화면 요소와 JavaScript 비동기 결과를 Python에서 사용합니다.
    def el(name):
        return document[name]

    async def wait(promise):
        future = aio.Future()
        promise.then(
            lambda value: future.set_result(value),
            lambda error: future.set_exception(RuntimeError(str(error))),
        )
        return await future

    def toast(message):
        el("toast").text = str(message)
        el("toast").hidden = False
        if state["toast_timer"] is not None:
            timer.clear_timeout(state["toast_timer"])
        state["toast_timer"] = timer.set_timeout(lambda: setattr(el("toast"), "hidden", True), 4500)

    # 영상과 모터 API는 같은 로컬 사이트에서만 호출합니다.
    async def request(path, data=None, body=None):
        if not local:
            raise RuntimeError("바탕화면의 드론 조종 시작으로 로컬 사이트를 여세요.")
        options = {"cache": "no-store", "signal": window.AbortSignal.timeout(25000)}
        if data is not None:
            options.update(
                method="POST", headers={"Content-Type": "application/json"}, body=json.dumps(data)
            )
        elif body is not None:
            options.update(method="POST", headers={"Content-Type": "image/jpeg"}, body=body)
        response = await wait(window.fetch("native/" + path, options))
        if not response.ok:
            text = await wait(response.text())
            try:
                text = json.loads(text).get("error", text)
            except ValueError:
                pass
            raise RuntimeError(text)
        return response

    async def api(path, data=None):
        return json.loads(await wait((await request(path, data)).text()))

    # 화면에는 실제 연결 상태와 앞바퀴 두 개의 현재 명령만 표시합니다.
    def render_controls():
        enabled = state["armed"] and not state["paused"]
        left, right = wheel_values(state["x"], state["y"], state["speed"]) if enabled else (0, 0)
        el("directionState").text = direction_name(state["x"], state["y"]) if enabled else "정지"
        el("powerValue").text = str(round(max(abs(left), abs(right)) * 100))
        el("leftPower").text, el("rightPower").text = str(round(left * 100)), str(
            round(right * 100)
        )
        el("gripperState").text = {1: "열림 동작", -1: "닫힘 동작", 0: "대기"}[state["grip"]]
        for name, value in (("gripperOpen", 1), ("gripperClose", -1)):
            el(name).disabled = not enabled
            el(name).classList.toggle("active", enabled and state["grip"] == value)
        el("joystick").setAttribute("aria-disabled", str(not enabled).lower())
        el("joystick").setAttribute("aria-valuenow", el("powerValue").text)
        el("armMotors").disabled = not state["connected"] or state["armed"] or state["paused"]
        el("motorMode").text = "실물 앞바퀴 2개" if state["connected"] else "모터 미연결"

    # 손을 놓으면 출력 0을 보내고 집게는 현재 각도를 유지합니다.
    def stop_drive(event=None):
        state["x"], state["y"], state["pointer"] = 0.0, 0.0, None
        state["keys"].clear()
        el("joystickKnob").style.transform = "translate(0,0)"
        render_controls()

    def stop_grip(event=None):
        state["grip"] = 0
        render_controls()

    def stop_all(event=None):
        stop_drive()
        stop_grip()

    # 좌우 앞바퀴의 차등 속도로 전진·후진·회전합니다.
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
        if not state["armed"] or state["paused"]:
            return
        event.preventDefault()
        state["pointer"] = event.pointerId
        el("joystick").setPointerCapture(event.pointerId)
        move_joystick(event)

    def bind_gripper(name, direction):
        def start(event):
            if state["armed"] and not state["paused"]:
                state["grip"] = direction
                el(name).setPointerCapture(event.pointerId)
                render_controls()

        el(name).bind("pointerdown", start)
        for kind in ("pointerup", "pointercancel", "lostpointercapture"):
            el(name).bind(kind, stop_grip)

    # 키보드 조종도 활성화된 상태에서만 받습니다.
    directions = {
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
        if el("settingsDialog").open or event.target.tagName in ("INPUT", "SELECT", "TEXTAREA"):
            return
        key = event.key.lower() if len(event.key) == 1 else event.key
        if key not in directions or not state["armed"] or state["paused"]:
            return
        event.preventDefault()
        if event.type == "keydown":
            state["keys"].add(key)
        else:
            state["keys"].discard(key)
        x = sum(directions[k][0] for k in state["keys"])
        y = sum(directions[k][1] for k in state["keys"])
        length = max(1, math.hypot(x, y))
        state["x"], state["y"] = x / length, y / length
        render_controls()

    # 실제 펌웨어가 응답한 포트만 연결됨으로 표시합니다.
    def motor_status(status):
        was_armed = state["armed"]
        state["connected"], state["armed"] = status["connected"], status["armed"]
        state["port"] = status.get("port", "")
        if was_armed and not state["armed"]:
            stop_all()
        text = (
            "모터 활성화됨"
            if state["armed"]
            else ("HC-06 연결됨 · 비활성" if state["connected"] else "HC-06 연결 안됨")
        )
        el("motorStatus").text = text
        el("motorError").text = status.get("error", "")
        angle = status.get("gripper_angle")
        el("gripHint").text = (
            f"SG90 · {angle}°" if angle is not None else "SG90 집게 · 누르는 동안 이동"
        )
        render_controls()

    async def refresh_ports(event=None):
        try:
            result = await api("motor/ports")
            select = el("motorPort")
            select.clear()
            for item in result["ports"]:
                option = document.createElement("option")
                option.value, option.text = item["port"], item["description"]
                select.appendChild(option)
            if state["port"]:
                select.value = state["port"]
            if not result["ports"]:
                el("motorError").text = "Windows에서 HC-06을 페어링한 뒤 포트 새로고침을 누르세요."
        except Exception as error:
            el("motorError").text = str(error)

    async def connect_motor(event=None):
        try:
            motor_status(await api("motor/connect", {"port": el("motorPort").value}))
            toast("HC-06 응답 확인. 모터는 아직 비활성입니다.")
        except Exception as error:
            el("motorError").text = str(error)

    async def arm_motor(event=None):
        try:
            stop_all()
            motor_status(await api("motor/arm", {}))
        except Exception as error:
            el("motorError").text = str(error)

    async def disconnect_motor(event=None):
        try:
            motor_status(await api("motor/disconnect", {}))
        except Exception as error:
            toast(error)

    # 새 조종 신호를 계속 보냅니다. 화면이 멈추면 서버와 Arduino가 별도로 정지합니다.
    async def motor_loop():
        while True:
            try:
                if state["armed"] and not state["paused"] and not document.hidden:
                    left, right = wheel_values(state["x"], state["y"], state["speed"])
                    status = await api(
                        "motor/command",
                        {
                            "left": round(left * 255),
                            "right": round(right * 255),
                            "grip": state["grip"],
                        },
                    )
                else:
                    status = await api("motor/status")
                motor_status(status)
            except Exception as error:
                state["connected"], state["armed"] = False, False
                stop_all()
                el("motorStatus").text = "모터 연결 확인 필요"
                el("motorError").text = str(error)
            await aio.sleep(0.08 if state["armed"] else 0.5)

    # 긴급 정지와 화면 이탈은 비활성화합니다. 복귀만으로 다시 켜지지 않습니다.
    def halt(event=None):
        state["armed"] = False
        stop_all()
        if local:
            aio.run(api("motor/stop", {}))

    def emergency(event=None):
        state["paused"] = True
        halt()
        el("pausedBanner").hidden = False

    def resume(event=None):
        state["paused"] = False
        el("pausedBanner").hidden = True
        render_controls()

    def speed_changed(event):
        state["speed"] = float(event.target.value) / 100
        el("speedValue").text = event.target.value + "%"

    # 감지는 Python OpenCV에서 합니다. 브라우저에는 실행 엔진을 넣지 않습니다.
    def vision_status():
        el("netCount").text = str(state["count"])
        el("visionState").text = (
            "그물 감지 꺼짐"
            if not state["enabled"]
            else (
                "OpenCV 모델 준비됨"
                if state["source"] == "none"
                else f"그물 {state['count']}개 감지"
            )
        )
        if not local:
            el("modelState").text = "OpenCV는 로컬 조종 사이트에서 실행합니다."
        elif state["vision_error"]:
            el("modelState").text = state["vision_error"]
        else:
            el("modelState").text = f"Python OpenCV DNN · {state['ms']}ms · 시험용 모델"

    async def configure_vision(event=None):
        state["enabled"] = el("detectionToggle").checked
        state["threshold"] = float(el("threshold").value) / 100
        el("thresholdValue").text = el("threshold").value + "%"
        try:
            status = await api(
                "vision/config", {"enabled": state["enabled"], "threshold": state["threshold"]}
            )
            state["model_ready"], state["vision_error"] = status["ready"], status["error"]
        except Exception as error:
            state["vision_error"] = str(error)
        vision_status()

    # 크기와 영상을 함께 갱신합니다. 로봇 모형과 뒷바퀴 그림은 없습니다.
    def show_frame(image, width, height):
        canvas = el("remoteFrame")
        if canvas.getAttribute("width") != str(width):
            canvas.attrs["width"] = width
        if canvas.getAttribute("height") != str(height):
            canvas.attrs["height"] = height
        canvas.getContext("2d").drawImage(image, 0, 0, width, height)
        state.update(width=width, height=height, frames=state["frames"] + 1)
        canvas.hidden = False
        el("welcome").hidden = True

    def release_video():
        state["generation"] += 1
        state["source"] = "none"
        state["count"] = 0
        el("fileVideo").pause()
        if state["media_image"] is not None:
            state["media_image"].close()
        if state["media_url"] is not None:
            window.URL.revokeObjectURL(state["media_url"])
        state["media_image"], state["media_url"] = None, None
        halt()

    # 드론 수신·추론·박스 표시를 끝낸 OpenCV JPEG를 그대로 가져옵니다.
    async def connect(event=None):
        if not local:
            toast("바탕화면의 드론 조종 시작을 실행하세요.")
            return
        try:
            mode = el("sourceMode").value
            if mode == "file":
                return
            release_video()
            if mode == "snapshot":
                url = el("snapshotUrl").value.strip()
                if not url.startswith(("http://", "https://")):
                    raise ValueError("JPEG 주소를 입력하세요.")
                state["source"] = "snapshot"
                aio.run(snapshot_loop(url, state["generation"]))
            else:
                await api(
                    "connect?host="
                    + el("droneAddress").value.strip()
                    + "&mode="
                    + el("jpegMode").value
                )
                state["source"] = "drone"
                aio.run(video_loop(state["generation"]))
            el("settingsDialog").close()
        except Exception as error:
            el("connectionError").text = str(error)

    async def video_loop(generation):
        while state["source"] == "drone" and generation == state["generation"]:
            try:
                status = await api("status")
                if not status["ready"]:
                    el("connectionState").text = status["error"] or "드론 영상 대기"
                    await aio.sleep(0.3)
                    continue
                vision = status["vision"]
                processed = vision["has_frame"] and state["enabled"]
                response = await request("vision/frame.jpg" if processed else "frame.jpg")
                image = await wait(window.createImageBitmap(await wait(response.blob())))
                if generation == state["generation"]:
                    show_frame(image, image.width, image.height)
                    state.update(
                        count=vision.get("count", 0) if processed else 0,
                        ms=vision.get("inference_ms", 0),
                        vision_error=vision["error"],
                    )
                    el("connectionState").text = "드론 영상 · OpenCV 연결됨"
                    vision_status()
                image.close()
            except Exception as error:
                el("connectionState").text = "영상 연결 확인: " + str(error)
            await aio.sleep(0.1)

    # 파일과 웹 JPEG도 프레임을 OpenCV로 보내 같은 방식으로 처리합니다.
    async def process_frame(image, width, height, generation):
        canvas = el("captureFrame")
        scale = min(1, 1280 / max(width, height))
        canvas.attrs["width"], canvas.attrs["height"] = round(width * scale), round(height * scale)
        canvas.getContext("2d").drawImage(image, 0, 0, round(width * scale), round(height * scale))
        future = aio.Future()
        canvas.toBlob(lambda blob: future.set_result(blob), "image/jpeg", 0.9)
        response = await request("vision/detect", body=await future)
        processed = await wait(window.createImageBitmap(await wait(response.blob())))
        if generation == state["generation"]:
            show_frame(processed, processed.width, processed.height)
            state["count"] = int(response.headers.get("X-Net-Count"))
            state["ms"] = int(response.headers.get("X-Inference-Ms"))
            vision_status()
        processed.close()

    async def choose_media(event):
        if not local:
            toast("OpenCV 감지는 로컬 조종 사이트에서 실행하세요.")
            return
        if not event.target.files.length:
            return
        release_video()
        await api("disconnect")
        file = event.target.files[0]
        try:
            if file.type.startswith("image/"):
                state["media_image"] = await wait(window.createImageBitmap(file))
            else:
                state["media_url"] = window.URL.createObjectURL(file)
                el("fileVideo").src = state["media_url"]
                await wait(el("fileVideo").play())
            state["source"] = "media"
            el("connectionState").text = "OpenCV 파일 감지 · " + file.name
            el("settingsDialog").close()
            aio.run(media_loop(state["generation"]))
        except Exception as error:
            toast(error)

    async def media_loop(generation):
        while state["source"] == "media" and generation == state["generation"]:
            try:
                image = state["media_image"]
                video = el("fileVideo")
                if image is not None:
                    await process_frame(image, image.width, image.height, generation)
                elif video.readyState >= 2:
                    await process_frame(video, video.videoWidth, video.videoHeight, generation)
            except Exception as error:
                state["vision_error"] = str(error)
                vision_status()
            await aio.sleep(0.1)

    async def snapshot_loop(url, generation):
        while state["source"] == "snapshot" and generation == state["generation"]:
            try:
                response = await wait(
                    window.fetch(
                        url, {"cache": "no-store", "signal": window.AbortSignal.timeout(3000)}
                    )
                )
                image = await wait(window.createImageBitmap(await wait(response.blob())))
                await process_frame(image, image.width, image.height, generation)
                image.close()
                el("connectionState").text = "JPEG 카메라 · OpenCV"
            except Exception as error:
                el("connectionState").text = "카메라 주소·CORS 확인: " + str(error)
            await aio.sleep(0.1)

    # 설정은 카메라와 모터를 같은 창에 모았습니다.
    def source_changed(event=None):
        mode = el("sourceMode").value
        for name, value in (
            ("fileSourceFields", "file"),
            ("snapshotSourceFields", "snapshot"),
            ("flowSourceFields", "flow"),
        ):
            el(name).hidden = mode != value
        el("pairButton").hidden = mode == "file"

    def open_settings(event=None):
        halt()
        el("settingsDialog").showModal()
        if local:
            aio.run(refresh_ports())

    def submit(event):
        event.preventDefault()
        aio.run(connect())

    async def fullscreen(event=None):
        try:
            await wait(
                document.exitFullscreen()
                if document.fullscreenElement
                else el("cockpit").requestFullscreen()
            )
        except Exception:
            pass

    def animation(timestamp):
        if timestamp - state["fps_time"] > 1000:
            el("frameRate").text = (
                str(round(state["frames"] * 1000 / max(1, timestamp - state["fps_time"]))) + " FPS"
            )
            el("frameSize").text = f"{state['width']} × {state['height']}"
            state["frames"], state["fps_time"] = 0, timestamp
        window.requestAnimationFrame(animation)

    # 마지막에 이벤트 연결을 모아 동작의 시작점을 쉽게 확인합니다.
    el("joystick").bind("pointerdown", start_joystick)
    el("joystick").bind("pointermove", move_joystick)
    for kind in ("pointerup", "pointercancel", "lostpointercapture"):
        el("joystick").bind(kind, stop_drive)
    bind_gripper("gripperOpen", 1)
    bind_gripper("gripperClose", -1)
    for kind in ("keydown", "keyup"):
        document.bind(kind, keyboard)
    window.bind("blur", halt)
    document.bind("visibilitychange", lambda event: halt() if document.hidden else None)
    for name in ("settingsButton", "cameraButton", "connectLaptop"):
        el(name).bind("click", open_settings)
    el("closeSettings").bind("click", lambda event: el("settingsDialog").close())
    el("connectionForm").bind("submit", submit)
    el("sourceMode").bind("change", source_changed)
    el("cameraFile").bind("change", lambda event: aio.run(choose_media(event)))
    el("refreshPorts").bind("click", lambda event: aio.run(refresh_ports()))
    el("connectMotor").bind("click", lambda event: aio.run(connect_motor()))
    el("disconnectMotor").bind("click", lambda event: aio.run(disconnect_motor()))
    el("armMotors").bind("click", lambda event: aio.run(arm_motor()))
    el("speed").bind("input", speed_changed)
    el("detectionToggle").bind("change", lambda event: aio.run(configure_vision()))
    el("threshold").bind("change", lambda event: aio.run(configure_vision()))
    el("stopButton").bind("click", emergency)
    el("resumeButton").bind("click", resume)
    el("fullscreenButton").bind("click", lambda event: aio.run(fullscreen()))
    el("sourceMode").value = "flow" if local else "file"
    el("localControl").hidden = local
    if local:
        el("connectionGuide").text = (
            "인터넷 없이 실행 중입니다. HC-06 연결 후 모터 활성화를 누르세요."
        )
    el("droneWifiButton").hidden = True
    source_changed()
    render_controls()
    vision_status()
    window.requestAnimationFrame(animation)
    if local:
        aio.run(configure_vision())
        aio.run(motor_loop())
        aio.run(connect())
