"""FLOW/WiFi UAV video-only UDP receiver, using documented wire-format facts.

Protocol references:
https://github.com/marshallrichards/turbodrone/blob/main/docs/research/wifi_uav.md
https://github.com/OpenIPC/decoder/blob/v2/docs/toys.md

Only video probes/fragment acknowledgements are sent. The flight-command area is empty.
"""

from collections import OrderedDict
import ipaddress
import select
import socket
import struct
import threading
import time


# 수신한 작은 영상 조각에서 순번, 크기, JPEG 내용을 읽습니다.
def parse_fragment(packet):
    if len(packet) < 56 or len(packet) > 1080 or packet[:2] != b"\x93\x01":
        return None
    if struct.unpack_from("<H", packet, 2)[0] != len(packet):
        return None
    sequence = struct.unpack_from("<Q", packet, 8)[0]
    base = struct.unpack_from("<Q", packet, 24)[0]
    index, total, length = struct.unpack_from("<III", packet, 32)
    width, height = struct.unpack_from("<HH", packet, 44)
    payload = packet[56:]
    if not sequence or not 1 <= total <= 1024 or index >= total or not 1 <= length <= total * 1024:
        return None
    need = min(1024, max(0, length - index * 1024))
    if need <= 0 or len(payload) < need or len(payload) > 1024:
        return None
    if not 0 < width <= 4096 or not 0 < height <= 4096:
        return None
    return dict(
        sequence=sequence,
        base=base,
        index=index,
        total=total,
        length=length,
        width=width,
        height=height,
        quality=packet[48],
        payload=payload[:need],
    )


# 순서가 바뀌거나 중복된 조각을 모아 JPEG 한 장으로 복원합니다.
class Frames:
    def __init__(self, header_loader, mode="zigzag"):
        self.load_header = header_loader
        self.mode = mode
        self.records = OrderedDict()
        self.newest = 0
        self.last_delivered = 0
        self.base = 0
        self.last_packet = 0.0
        self.headers = {}

    # 최근 네 프레임만 보관하고 모든 조각이 모이면 사진을 반환합니다.
    def add(self, packet, now=None):
        data = parse_fragment(packet)
        if data is None:
            return None
        now = time.monotonic() if now is None else now
        seq = data["sequence"]
        if seq + 64 < self.newest:
            return None
        self.newest = max(self.newest, seq)
        self.last_packet = now
        if data["base"] < seq:
            self.base = max(self.base, data["base"])
        if seq not in self.records:
            self.records[seq] = {**data, "parts": {}, "complete": False}
            self.records.move_to_end(seq)
            while len(self.records) > 4:
                self.records.popitem(last=False)
        record = self.records[seq]
        if any(record[k] != data[k] for k in ("total", "length", "width", "height")):
            return None
        record["parts"][data["index"]] = data["payload"]
        if record["complete"] or len(record["parts"]) != record["total"]:
            return None
        record["complete"] = True
        if seq <= self.last_delivered:
            return None
        body = b"".join(record["parts"][i] for i in range(record["total"]))[: record["length"]]
        quality = record["quality"] if 1 <= record["quality"] <= 100 else 50
        key = (quality, record["width"], record["height"], self.mode)
        if key not in self.headers:
            self.headers[key] = self.jpeg_header(*key)
            if len(self.headers) > 16:
                self.headers.pop(next(iter(self.headers)))
        self.last_delivered = seq
        return self.headers[key] + body + (b"" if body.endswith(b"\xff\xd9") else b"\xff\xd9")

    # 드론이 생략한 JPEG 헤더에 실제 해상도와 색상 표를 넣습니다.
    def jpeg_header(self, quality, width, height, mode):
        header = bytearray(self.load_header(quality if mode == "zigzag" else 50))
        pos = 2
        while pos + 4 <= len(header):
            marker = header[pos + 1]
            length = int.from_bytes(header[pos + 2 : pos + 4], "big")
            if marker == 0xC0:
                header[pos + 5 : pos + 9] = struct.pack(">HH", height, width)
            if marker == 0xDB and mode == "raster":
                # 색상이 다른 드론 펌웨어는 양자화 표의 순서를 바꿔 맞춥니다.
                order = []
                for diagonal in range(15):
                    coordinates = [
                        (row, diagonal - row) for row in range(8) if 0 <= diagonal - row < 8
                    ]
                    if diagonal % 2 == 0:
                        coordinates.reverse()
                    order.extend(row * 8 + col for row, col in coordinates)
                at = pos + 4
                while at < pos + 2 + length:
                    if header[at] >> 4:
                        raise ValueError("Only 8-bit JPEG quantization supported")
                    table = header[at + 1 : at + 65]
                    raster = bytearray(64)
                    for value, index in zip(table, order):
                        raster[index] = value
                    header[at + 1 : at + 65] = raster
                    at += 65
            if marker == 0xDA:
                break
            pos += 2 + length
        return bytes(header)

    # 받은 조각 목록을 드론에 알려 영상 전송이 이어지도록 합니다.
    def acknowledgement(self, now=None):
        now = time.monotonic() if now is None else now
        records = []
        eligible = [
            (seq, r) for seq, r in self.records.items() if seq > self.base and self.newest - seq < 5
        ]
        for seq, r in eligible:
            if seq == self.newest and not r["complete"] and now - self.last_packet < 0.019:
                continue
            words = (r["total"] + 31) // 32
            bitmap = []
            for word in range(words):
                value = 0
                for bit in range(32):
                    index = word * 32 + bit
                    if index >= r["total"] or index in r["parts"]:
                        value |= 1 << bit
                bitmap.append(value)
            records.append(
                struct.pack("<QII", seq, 1 if r["complete"] else 0, 16 + 4 * words)
                + struct.pack("<" + "I" * words, *bitmap)
            )
        if eligible and all(r["complete"] for _, r in eligible) and now - self.last_packet >= 0.019:
            records.append(struct.pack("<QII", self.newest + 1, 3, 16))
        header = bytearray(88)
        header[:8] = b"\xef\x02\0\0\x02\x02\0\x01"
        struct.pack_into("<I", header, 8, len(records))
        # 12~81 바이트는 0으로 둡니다. 이 영역의 비행 조종값은 쓰지 않습니다.
        header[82:86] = bytes.fromhex("324b142d")
        result = header + b"".join(records)
        struct.pack_into("<H", result, 2, len(result))
        return bytes(result)


# 영상 통신은 별도 스레드에서 실행하고 최신 사진 한 장만 전달합니다.
class Receiver:
    def __init__(self, header_loader):
        self.header_loader = header_loader
        self.lock = threading.Lock()
        self.jpeg = None
        self.sequence = 0
        self.timestamp = 0.0
        self.error = "드론 Wi-Fi에 연결한 뒤 영상 연결을 누르세요."
        self.port = None
        self.stop_event = threading.Event()
        self.thread = None

    # 드론의 사설 IP 주소를 검사하고 이전 연결을 닫은 뒤 시작합니다.
    def connect(self, host="192.168.169.1", mode="zigzag"):
        address = ipaddress.ip_address(host)
        if address.version != 4 or not address.is_private or address.is_loopback:
            raise ValueError("드론의 사설 IPv4 주소를 입력하세요.")
        if mode not in ("zigzag", "raster", "q50"):
            raise ValueError("Unknown JPEG mode")
        self.close()
        self.stop_event = threading.Event()
        with self.lock:
            self.jpeg = None
            self.sequence = 0
            self.timestamp = 0.0
            self.port = None
            self.error = f"{host} 영상 응답 대기 · FLOW Wi-Fi 연결을 확인하세요."
        self.thread = threading.Thread(
            target=self._run, args=(str(address), mode, self.stop_event), daemon=True
        )
        self.thread.start()

    # 최근 1.5초 안에 사진을 받았는지 화면에 알려줍니다.
    def status(self):
        with self.lock:
            ready = self.jpeg is not None and time.monotonic() - self.timestamp < 1.5
            return {
                "ready": ready,
                "sequence": self.sequence,
                "error": self.error,
                "port": self.port,
                "simulated": True,
            }

    # 오래된 영상은 재사용하지 않고 새 연결을 기다립니다.
    def frame(self):
        with self.lock:
            if self.jpeg is None or time.monotonic() - self.timestamp > 1.5:
                return None, self.sequence
            return self.jpeg, self.sequence

    # Wi-Fi를 바꾸는 동안 통신이 실패해도 종료하지 않고 다시 연결합니다.
    def _run(self, host, mode, stop):
        while not stop.is_set():
            self._receive(host, mode, stop)
            stop.wait(1)

    # 두 영상 포트를 확인하고 응답하는 포트에서 계속 수신합니다.
    def _receive(self, host, mode, stop):
        sockets = {}
        active = None
        frames = Frames(self.header_loader, mode)
        last_probe = {8800: 0.0, 8801: 0.0}
        last_ack = 0.0
        suspicion = 0
        try:
            for port in (8800, 8801):
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2 * 1024 * 1024)
                sock.bind(("0.0.0.0", 0))
                sock.setblocking(False)
                sockets[sock] = port
            while not stop.is_set():
                now = time.monotonic()
                if active and now - frames.last_packet > 3:
                    active = None
                    frames = Frames(self.header_loader, mode)
                    with self.lock:
                        self.error = "영상이 끊겼습니다. 드론 Wi-Fi를 확인하세요."
                if active is None:
                    for sock, port in sockets.items():
                        if now - last_probe[port] > (0.1 if port == 8800 else 0.2):
                            sock.sendto(b"\xef\0\x04\0", (host, port))
                            last_probe[port] = now
                elif now - last_ack > (0.025 if sockets[active] == 8800 else 0.05):
                    active.sendto(frames.acknowledgement(now), (host, sockets[active]))
                    last_ack = now
                ready, _, _ = select.select(list(sockets), [], [], 0.01)
                for sock in ready:
                    packet, address = sock.recvfrom(2048)
                    if address[0] != host or (active is not None and active is not sock):
                        continue
                    parsed = parse_fragment(packet)
                    if parsed is None:
                        continue
                    if parsed["sequence"] + 64 < frames.newest:
                        suspicion += 1
                        if suspicion >= 8:
                            frames = Frames(self.header_loader, mode)
                            suspicion = 0
                        else:
                            continue
                    else:
                        suspicion = 0
                    active = sock
                    image = frames.add(packet, now)
                    if image:
                        with self.lock:
                            self.jpeg = image
                            self.sequence += 1
                            self.timestamp = now
                            self.port = sockets[sock]
                            self.error = ""
        except Exception as exc:
            with self.lock:
                self.error = "드론 영상 수신 오류: " + str(exc)
        finally:
            for sock in sockets:
                sock.close()

    # 정지 신호를 보내고 수신 스레드가 끝나기를 기다립니다.
    def close(self):
        self.stop_event.set()
        thread = self.thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=2)
        self.thread = None
