import argparse
import asyncio
import ctypes
import json
import secrets
import socket
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from ctypes import wintypes
from fractions import Fraction
from pathlib import Path
from typing import Any

from aiohttp import web

try:
    from aiortc import VideoStreamTrack
except ImportError:
    VideoStreamTrack = object  # type: ignore[misc,assignment]

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000
INPUT_MOUSE = 0
INPUT_HARDWARE = 2
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79
ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

if sys.platform != "win32":
    raise SystemExit("The WebRTC tablet server injects Windows mouse input and must run on Windows.")

USER32 = ctypes.WinDLL("user32", use_last_error=True)


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", INPUT_UNION)]


USER32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
USER32.SendInput.restype = wintypes.UINT
USER32.GetSystemMetrics.argtypes = (ctypes.c_int,)
USER32.GetSystemMetrics.restype = ctypes.c_int


def _send_mouse_input(dx: int = 0, dy: int = 0, flags: int = 0, mouse_data: int = 0) -> None:
    event = INPUT(
        type=INPUT_MOUSE,
        union=INPUT_UNION(
            mi=MOUSEINPUT(
                dx=dx,
                dy=dy,
                mouseData=mouse_data,
                dwFlags=flags,
                time=0,
                dwExtraInfo=0,
            )
        ),
    )
    sent = USER32.SendInput(1, ctypes.byref(event), ctypes.sizeof(event))
    if sent != 1:
        raise ctypes.WinError(ctypes.get_last_error())


def virtual_screen_rect() -> dict[str, int]:
    return {
        "left": USER32.GetSystemMetrics(SM_XVIRTUALSCREEN),
        "top": USER32.GetSystemMetrics(SM_YVIRTUALSCREEN),
        "width": USER32.GetSystemMetrics(SM_CXVIRTUALSCREEN),
        "height": USER32.GetSystemMetrics(SM_CYVIRTUALSCREEN),
    }


def move_mouse_to_screen_point(x: int, y: int) -> None:
    rect = virtual_screen_rect()
    width = max(1, rect["width"] - 1)
    height = max(1, rect["height"] - 1)
    normalized_x = round((x - rect["left"]) * 65535 / width)
    normalized_y = round((y - rect["top"]) * 65535 / height)
    _send_mouse_input(
        dx=max(0, min(65535, normalized_x)),
        dy=max(0, min(65535, normalized_y)),
        flags=MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
    )


def left_mouse_down() -> None:
    _send_mouse_input(flags=MOUSEEVENTF_LEFTDOWN)


def left_mouse_up() -> None:
    _send_mouse_input(flags=MOUSEEVENTF_LEFTUP)


def mouse_wheel(delta: int) -> None:
    _send_mouse_input(flags=MOUSEEVENTF_WHEEL, mouse_data=delta)


def get_lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def monitor_rect(monitor_id: int) -> dict[str, int]:
    import mss

    with mss.mss() as sct:
        index = max(1, min(monitor_id, len(sct.monitors) - 1))
        return dict(sct.monitors[index])


def scale_size(width: int, height: int, max_width: int) -> tuple[int, int]:
    if max_width <= 0 or width <= max_width:
        return width, height
    target_width = max_width
    target_height = max(1, round(height * target_width / width))
    return target_width, target_height


class ScreenVideoTrack(VideoStreamTrack):  # type: ignore[misc,valid-type]
    def __init__(self, monitor_id: int, fps: int, max_width: int) -> None:
        super().__init__()
        self.monitor = monitor_rect(monitor_id)
        self.fps = max(1, min(fps, 60))
        self.max_width = max_width
        self.frame_interval = 1 / self.fps
        self.next_frame_time = time.perf_counter()
        self.pts = 0
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="screen-capture")
        self._thread_local: Any = None

    async def recv(self) -> Any:
        from av import VideoFrame

        now = time.perf_counter()
        if self.next_frame_time > now:
            await asyncio.sleep(self.next_frame_time - now)
        self.next_frame_time = max(self.next_frame_time + self.frame_interval, time.perf_counter())

        loop = asyncio.get_running_loop()
        rgb = await loop.run_in_executor(self.executor, self._grab_rgb)
        height, width, _ = rgb.shape
        frame = VideoFrame.from_ndarray(rgb, format="rgb24")
        target_width, target_height = scale_size(width, height, self.max_width)
        if target_width != width or target_height != height:
            frame = frame.reformat(width=target_width, height=target_height)
        frame.pts = self.pts
        frame.time_base = Fraction(1, 90000)
        self.pts += round(90000 / self.fps)
        return frame

    def _grab_rgb(self) -> Any:
        import mss
        import numpy as np

        if self._thread_local is None:
            import threading

            self._thread_local = threading.local()
        sct = getattr(self._thread_local, "sct", None)
        if sct is None:
            sct = mss.mss()
            self._thread_local.sct = sct
        shot = sct.grab(self.monitor)
        return np.frombuffer(shot.rgb, dtype=np.uint8).reshape(shot.height, shot.width, 3).copy()

    def stop(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)


def clamp_ratio(value: Any) -> float:
    return max(0.0, min(1.0, float(value)))


def ratio_to_screen_point(monitor: dict[str, int], x_ratio: float, y_ratio: float) -> tuple[int, int]:
    x = int(monitor["left"] + x_ratio * max(1, monitor["width"] - 1))
    y = int(monitor["top"] + y_ratio * max(1, monitor["height"] - 1))
    return x, y


def handle_pointer_payload(payload: dict[str, Any], monitor: dict[str, int]) -> None:
    if payload.get("type") != "pointer":
        raise ValueError("unsupported message type")
    action = payload.get("action")
    if action == "wheel":
        delta = max(-1200, min(1200, int(payload.get("delta", 0))))
        if delta:
            mouse_wheel(delta)
        return

    x_ratio = clamp_ratio(payload.get("x"))
    y_ratio = clamp_ratio(payload.get("y"))
    x, y = ratio_to_screen_point(monitor, x_ratio, y_ratio)

    if action == "down":
        move_mouse_to_screen_point(x, y)
        left_mouse_down()
    elif action == "up":
        move_mouse_to_screen_point(x, y)
        left_mouse_up()
    elif action == "move":
        move_mouse_to_screen_point(x, y)
    else:
        raise ValueError(f"unsupported pointer action: {action}")


class StrokeReplayer:
    def __init__(self, monitor: dict[str, int]) -> None:
        self.monitor = monitor
        self.queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self.task = asyncio.create_task(self._run())
        self.mouse_is_down = False

    def submit(self, raw: str) -> None:
        payload = json.loads(raw)
        if payload.get("type") == "pointer":
            handle_pointer_payload(payload, self.monitor)
            return
        if payload.get("type") != "stroke":
            raise ValueError("unsupported message type")
        self.queue.put_nowait(payload)

    def stop(self) -> None:
        self.task.cancel()
        if self.mouse_is_down:
            try:
                left_mouse_up()
            finally:
                self.mouse_is_down = False

    async def _run(self) -> None:
        while True:
            payload = await self.queue.get()
            if payload is None:
                return
            try:
                await self._replay_stroke(payload)
            except Exception as exc:
                print(f"[stroke error] {exc}", flush=True)
                if self.mouse_is_down:
                    try:
                        left_mouse_up()
                    finally:
                        self.mouse_is_down = False

    async def _replay_stroke(self, payload: dict[str, Any]) -> None:
        points = self._normalize_points(payload.get("points"))
        if not points:
            return

        first = points[0]
        x, y = ratio_to_screen_point(self.monitor, first["x"], first["y"])
        move_mouse_to_screen_point(x, y)
        left_mouse_down()
        self.mouse_is_down = True

        previous_t = first["t"]
        for point in points[1:]:
            delay = max(0.0, min(0.008, (point["t"] - previous_t) / 1000 * 0.45))
            if delay:
                await asyncio.sleep(delay)
            x, y = ratio_to_screen_point(self.monitor, point["x"], point["y"])
            move_mouse_to_screen_point(x, y)
            previous_t = point["t"]

        left_mouse_up()
        self.mouse_is_down = False

    def _normalize_points(self, raw_points: Any) -> list[dict[str, float]]:
        if not isinstance(raw_points, list):
            raise ValueError("stroke.points must be a list")
        normalized: list[dict[str, float]] = []
        for point in raw_points[:2048]:
            if not isinstance(point, dict):
                continue
            normalized.append(
                {
                    "x": clamp_ratio(point.get("x")),
                    "y": clamp_ratio(point.get("y")),
                    "t": max(0.0, float(point.get("t", 0))),
                }
            )
        return normalized


async def index(_: web.Request) -> web.FileResponse:
    return web.FileResponse(STATIC_DIR / "index.html")


async def health(_: web.Request) -> web.Response:
    return web.json_response({"ok": True})


async def offer(request: web.Request) -> web.Response:
    from aiortc import RTCPeerConnection, RTCSessionDescription

    app = request.app
    if request.query.get("token") != app["token"]:
        raise web.HTTPUnauthorized(text="invalid token")

    params = await request.json()
    fps = max(1, min(int(params.get("fps", app["fps"])), 60))
    max_width = max(640, min(int(params.get("maxWidth", app["max_width"])), 3840))
    monitor_id = max(1, int(params.get("monitor", app["monitor"])))

    pc = RTCPeerConnection()
    app["pcs"].add(pc)
    track = ScreenVideoTrack(monitor_id=monitor_id, fps=fps, max_width=max_width)
    pc.addTrack(track)
    replayers: list[StrokeReplayer] = []

    @pc.on("datachannel")
    def on_datachannel(channel: Any) -> None:
        if channel.label != "pointer":
            channel.close()
            return
        replayer = StrokeReplayer(track.monitor)
        replayers.append(replayer)

        @channel.on("message")
        def on_message(message: Any) -> None:
            if not isinstance(message, str):
                return
            try:
                replayer.submit(message)
            except Exception as exc:
                print(f"[pointer error] {exc}", flush=True)

        @channel.on("close")
        def on_close() -> None:
            replayer.stop()
            if replayer in replayers:
                replayers.remove(replayer)

    @pc.on("connectionstatechange")
    async def on_connectionstatechange() -> None:
        print(f"[webrtc] state={pc.connectionState}", flush=True)
        if pc.connectionState in {"failed", "closed", "disconnected"}:
            await pc.close()
            track.stop()
            for replayer in list(replayers):
                replayer.stop()
            replayers.clear()
            app["pcs"].discard(pc)

    await pc.setRemoteDescription(RTCSessionDescription(sdp=params["sdp"], type=params["type"]))
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return web.json_response(
        {
            "sdp": pc.localDescription.sdp,
            "type": pc.localDescription.type,
            "monitor": track.monitor,
            "fps": fps,
            "maxWidth": max_width,
        }
    )


async def on_shutdown(app: web.Application) -> None:
    pcs = list(app["pcs"])
    for pc in pcs:
        await pc.close()
    app["pcs"].clear()


def create_app(token: str, monitor: int, fps: int, max_width: int) -> web.Application:
    app = web.Application()
    app["token"] = token
    app["monitor"] = monitor
    app["fps"] = fps
    app["max_width"] = max_width
    app["pcs"] = set()
    app.router.add_get("/", index)
    app.router.add_get("/health", health)
    app.router.add_post("/offer", offer)
    app.router.add_static("/static", STATIC_DIR)
    app.on_shutdown.append(on_shutdown)
    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Low-latency WebRTC iPad tablet server.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8790)
    parser.add_argument("--token", default=None)
    parser.add_argument("--monitor", type=int, default=1)
    parser.add_argument("--fps", type=int, default=45)
    parser.add_argument("--max-width", type=int, default=1600)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    token = args.token or secrets.token_urlsafe(12)
    app = create_app(token=token, monitor=args.monitor, fps=args.fps, max_width=args.max_width)
    lan_ip = get_lan_ip()
    print("WebRTC tablet server is running.", flush=True)
    print(f"Open on iPad: http://{lan_ip}:{args.port}/?token={token}", flush=True)
    print(f"Default capture: monitor={args.monitor}, fps={args.fps}, max_width={args.max_width}", flush=True)
    web.run_app(app, host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
