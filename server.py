import argparse
import asyncio
import ctypes
import json
import secrets
import socket
import sys
from io import BytesIO
from pathlib import Path
from typing import Any
from ctypes import wintypes

from aiohttp import web
from PIL import Image


def app_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


ROOT = app_root()
STATIC_DIR = ROOT / "static"

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000
INPUT_KEYBOARD = 1
INPUT_MOUSE = 0
INPUT_HARDWARE = 2
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79
VK_BACK = 0x08
VK_RETURN = 0x0D
ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong
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


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
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
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", INPUT_UNION)]


USER32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
USER32.SendInput.restype = wintypes.UINT
USER32.GetSystemMetrics.argtypes = (ctypes.c_int,)
USER32.GetSystemMetrics.restype = ctypes.c_int


def _send_keyboard_input(vk: int = 0, scan: int = 0, flags: int = 0) -> None:
    event = INPUT(
        type=INPUT_KEYBOARD,
        union=INPUT_UNION(
            ki=KEYBDINPUT(
                wVk=vk,
                wScan=scan,
                dwFlags=flags,
                time=0,
                dwExtraInfo=0,
            )
        ),
    )
    sent = USER32.SendInput(1, ctypes.byref(event), ctypes.sizeof(event))
    if sent != 1:
        raise ctypes.WinError(ctypes.get_last_error())


def _send_mouse_input(dx: int = 0, dy: int = 0, flags: int = 0) -> None:
    event = INPUT(
        type=INPUT_MOUSE,
        union=INPUT_UNION(
            mi=MOUSEINPUT(
                dx=dx,
                dy=dy,
                mouseData=0,
                dwFlags=flags,
                time=0,
                dwExtraInfo=0,
            )
        ),
    )
    sent = USER32.SendInput(1, ctypes.byref(event), ctypes.sizeof(event))
    if sent != 1:
        raise ctypes.WinError(ctypes.get_last_error())


def press_key(vk: int) -> None:
    _send_keyboard_input(vk=vk)
    _send_keyboard_input(vk=vk, flags=KEYEVENTF_KEYUP)


def type_text(text: str) -> None:
    # SendInput with KEYEVENTF_UNICODE accepts UTF-16 code units, so encode first
    # to preserve non-BMP characters such as emoji.
    data = text.encode("utf-16-le")
    for i in range(0, len(data), 2):
        code_unit = data[i] | (data[i + 1] << 8)
        if code_unit == 0x000A:
            press_key(VK_RETURN)
            continue
        if code_unit == 0x000D:
            continue
        _send_keyboard_input(scan=code_unit, flags=KEYEVENTF_UNICODE)
        _send_keyboard_input(scan=code_unit, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)


def backspace(count: int) -> None:
    for _ in range(max(0, min(count, 1000))):
        press_key(VK_BACK)


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


def capture_jpeg(monitor_id: int, quality: int) -> tuple[dict[str, int], bytes]:
    import mss

    with mss.mss() as sct:
        monitor_index = max(1, min(monitor_id, len(sct.monitors) - 1))
        monitor = dict(sct.monitors[monitor_index])
        shot = sct.grab(monitor)
        image = Image.frombytes("RGB", shot.size, shot.rgb)
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=quality, optimize=False)
        return monitor, buffer.getvalue()


class TextSession:
    def __init__(self) -> None:
        self.text = ""

    def replace(self, new_text: str) -> None:
        prefix_len = common_prefix_len(self.text, new_text)
        delete_count = len(list(self.text[prefix_len:]))
        insert_text = new_text[prefix_len:]
        if delete_count:
            backspace(delete_count)
        if insert_text:
            type_text(insert_text)
        self.text = new_text

    def reset(self) -> None:
        self.text = ""


def get_lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def common_prefix_len(left: str, right: str) -> int:
    length = min(len(left), len(right))
    index = 0
    while index < length and left[index] == right[index]:
        index += 1
    return index


def validate_ops(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get("type") != "ops":
        raise ValueError("unsupported message type")
    ops = payload.get("ops")
    if not isinstance(ops, list):
        raise ValueError("ops must be a list")
    normalized: list[dict[str, Any]] = []
    for op in ops:
        if not isinstance(op, dict):
            raise ValueError("op must be an object")
        op_type = op.get("type")
        if op_type == "insert":
            text = op.get("text")
            if not isinstance(text, str):
                raise ValueError("insert.text must be a string")
            if text:
                normalized.append({"type": "insert", "text": text[:5000]})
        elif op_type == "enter":
            normalized.append({"type": "enter"})
        elif op_type == "backspace":
            count = op.get("count")
            if not isinstance(count, int):
                raise ValueError("backspace.count must be an integer")
            if count > 0:
                normalized.append({"type": "backspace", "count": min(count, 1000)})
        else:
            raise ValueError(f"unsupported op type: {op_type}")
    return normalized


def create_app(token: str) -> web.Application:
    app = web.Application()
    session = TextSession()

    async def index(request: web.Request) -> web.FileResponse:
        return web.FileResponse(STATIC_DIR / "index.html")

    async def health(_: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    async def tablet(request: web.Request) -> web.FileResponse:
        return web.FileResponse(STATIC_DIR / "tablet.html")

    async def screen_handler(request: web.Request) -> web.WebSocketResponse:
        if request.query.get("token") != token:
            raise web.HTTPUnauthorized(text="invalid token")

        fps = max(1, min(int(request.query.get("fps", "24")), 30))
        quality = max(25, min(int(request.query.get("quality", "58")), 85))
        monitor_id = max(1, int(request.query.get("monitor", "1")))
        interval = 1 / fps

        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=16 * 1024 * 1024)
        await ws.prepare(request)
        peer = request.remote or "unknown"
        print(f"[screen] connected: {peer}", flush=True)

        last_monitor: dict[str, int] | None = None
        try:
            while not ws.closed:
                started = asyncio.get_running_loop().time()
                monitor, frame = await asyncio.to_thread(capture_jpeg, monitor_id, quality)
                if monitor != last_monitor:
                    await ws.send_json(
                        {
                            "type": "screen_meta",
                            "monitor": monitor,
                            "fps": fps,
                            "quality": quality,
                        }
                    )
                    last_monitor = monitor
                await ws.send_bytes(frame)
                elapsed = asyncio.get_running_loop().time() - started
                await asyncio.sleep(max(0, interval - elapsed))
        except ConnectionResetError:
            pass
        finally:
            print(f"[screen] disconnected: {peer}", flush=True)
        return ws

    async def pointer_handler(request: web.Request) -> web.WebSocketResponse:
        if request.query.get("token") != token:
            raise web.HTTPUnauthorized(text="invalid token")

        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        peer = request.remote or "unknown"
        print(f"[pointer] connected: {peer}", flush=True)

        async for msg in ws:
            if msg.type != web.WSMsgType.TEXT:
                continue
            try:
                payload = json.loads(msg.data)
                if payload.get("token") != token:
                    raise ValueError("invalid token")
                if payload.get("type") != "pointer":
                    raise ValueError("unsupported pointer message")

                monitor = payload.get("monitor")
                if not isinstance(monitor, dict):
                    raise ValueError("missing monitor metadata")
                x_ratio = float(payload.get("x"))
                y_ratio = float(payload.get("y"))
                x_ratio = max(0.0, min(1.0, x_ratio))
                y_ratio = max(0.0, min(1.0, y_ratio))
                x = int(monitor["left"] + x_ratio * max(1, monitor["width"] - 1))
                y = int(monitor["top"] + y_ratio * max(1, monitor["height"] - 1))
                action = payload.get("action")

                move_mouse_to_screen_point(x, y)
                if action == "down":
                    left_mouse_down()
                elif action == "up":
                    left_mouse_up()
                elif action == "move":
                    pass
                else:
                    raise ValueError(f"unsupported pointer action: {action}")
            except Exception as exc:
                print(f"[pointer error] {exc}", flush=True)
                await ws.send_json({"type": "error", "message": str(exc)})

        print(f"[pointer] disconnected: {peer}", flush=True)
        return ws

    async def websocket_handler(request: web.Request) -> web.WebSocketResponse:
        if request.query.get("token") != token:
            raise web.HTTPUnauthorized(text="invalid token")

        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        peer = request.remote or "unknown"
        print(f"[ws] connected: {peer}", flush=True)
        await ws.send_json({"type": "ready"})

        async for msg in ws:
            if msg.type != web.WSMsgType.TEXT:
                continue
            try:
                payload = json.loads(msg.data)
                if payload.get("token") != token:
                    raise ValueError("invalid token")
                if payload.get("type") == "sync_text":
                    text = payload.get("text")
                    if not isinstance(text, str):
                        raise ValueError("sync_text.text must be a string")
                    text = text[:5000]
                    print(
                        f"[sync] replace {len(session.text)} chars -> {len(text)} chars: {text!r}",
                        flush=True,
                    )
                    session.replace(text)
                elif payload.get("type") == "reset_session":
                    print("[sync] reset session", flush=True)
                    session.reset()
                else:
                    ops = validate_ops(payload)
                    for op in ops:
                        if op["type"] == "insert":
                            print(f"[inject] insert {len(op['text'])} chars: {op['text']!r}", flush=True)
                            type_text(op["text"])
                        elif op["type"] == "enter":
                            print("[inject] enter", flush=True)
                            press_key(VK_RETURN)
                        elif op["type"] == "backspace":
                            print(f"[inject] backspace {op['count']}", flush=True)
                            backspace(op["count"])
                await ws.send_json({"type": "ack", "seq": payload.get("seq")})
            except Exception as exc:
                print(f"[error] {exc}", flush=True)
                await ws.send_json({"type": "error", "message": str(exc)})

        print(f"[ws] disconnected: {peer}", flush=True)
        return ws

    app.router.add_get("/", index)
    app.router.add_get("/tablet", tablet)
    app.router.add_get("/health", health)
    app.router.add_get("/ws", websocket_handler)
    app.router.add_get("/screen", screen_handler)
    app.router.add_get("/pointer", pointer_handler)
    app.router.add_static("/static", STATIC_DIR)
    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phone realtime input bridge for Windows.")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host, default: 0.0.0.0")
    parser.add_argument("--port", type=int, default=8787, help="Bind port, default: 8787")
    parser.add_argument("--token", default=None, help="Session token. Defaults to a random token.")
    parser.add_argument("--test-text", default=None, help="Type text into the current Windows focus after a countdown, then exit.")
    return parser.parse_args()


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("This program injects text with Windows SendInput and must run on Windows.")

    args = parse_args()
    if args.test_text is not None:
        print("Focus the target input box within 3 seconds...", flush=True)
        import time

        time.sleep(3)
        type_text(args.test_text)
        print("Test text sent.", flush=True)
        return

    token = args.token or secrets.token_urlsafe(12)
    app = create_app(token)

    lan_ip = get_lan_ip()
    print("Phone realtime input bridge is running.")
    print(f"Open on phone: http://{lan_ip}:{args.port}/?token={token}")
    print("Keep the target app focused on this PC; phone input will be typed there.")
    web.run_app(app, host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
