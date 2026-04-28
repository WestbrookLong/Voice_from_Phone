import argparse
import asyncio
import ctypes
import json
import secrets
import socket
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Any

from aiohttp import web


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
TOKEN_FILE = ROOT / ".fps_controller_token"

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008

ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

if sys.platform != "win32":
    raise SystemExit("This controller injects Windows input and must run on Windows.")

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


class INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", INPUT_UNION)]


USER32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
USER32.SendInput.restype = wintypes.UINT


SCAN_CODES: dict[str, int] = {
    "KeyW": 0x11,
    "KeyA": 0x1E,
    "KeyS": 0x1F,
    "KeyD": 0x20,
    "KeyQ": 0x10,
    "KeyE": 0x12,
    "KeyR": 0x13,
    "KeyF": 0x21,
    "Digit1": 0x02,
    "Digit2": 0x03,
    "Digit3": 0x04,
    "Digit4": 0x05,
    "Space": 0x39,
    "ShiftLeft": 0x2A,
    "ControlLeft": 0x1D,
    "AltLeft": 0x38,
    "Tab": 0x0F,
    "Escape": 0x01,
}

MOUSE_BUTTON_FLAGS = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}


def _send_input(event: INPUT) -> None:
    sent = USER32.SendInput(1, ctypes.byref(event), ctypes.sizeof(event))
    if sent != 1:
        raise ctypes.WinError(ctypes.get_last_error())


def send_mouse_input(dx: int = 0, dy: int = 0, flags: int = 0, mouse_data: int = 0) -> None:
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
    _send_input(event)


def move_mouse_relative(dx: float, dy: float, sensitivity: float) -> None:
    scaled_dx = int(round(dx * sensitivity))
    scaled_dy = int(round(dy * sensitivity))
    if scaled_dx == 0 and scaled_dy == 0:
        return
    send_mouse_input(dx=scaled_dx, dy=scaled_dy, flags=MOUSEEVENTF_MOVE)


def set_mouse_button(button: str, down: bool) -> None:
    if button not in MOUSE_BUTTON_FLAGS:
        raise ValueError(f"unsupported mouse button: {button}")
    down_flag, up_flag = MOUSE_BUTTON_FLAGS[button]
    send_mouse_input(flags=down_flag if down else up_flag)


def wheel(delta: int) -> None:
    send_mouse_input(flags=MOUSEEVENTF_WHEEL, mouse_data=int(delta))


def set_key(code: str, down: bool) -> None:
    scan_code = SCAN_CODES.get(code)
    if scan_code is None:
        raise ValueError(f"unsupported key code: {code}")
    flags = KEYEVENTF_SCANCODE | (0 if down else KEYEVENTF_KEYUP)
    event = INPUT(
        type=INPUT_KEYBOARD,
        union=INPUT_UNION(
            ki=KEYBDINPUT(
                wVk=0,
                wScan=scan_code,
                dwFlags=flags,
                time=0,
                dwExtraInfo=0,
            )
        ),
    )
    _send_input(event)


class InputSession:
    def __init__(self, sensitivity: float) -> None:
        self.sensitivity = sensitivity
        self.keys_down: set[str] = set()
        self.mouse_down: set[str] = set()

    def handle(self, message: dict[str, Any]) -> None:
        kind = message.get("type")
        if kind == "look":
            move_mouse_relative(float(message.get("dx", 0)), float(message.get("dy", 0)), self.sensitivity)
        elif kind == "look_batch":
            for item in message.get("events", [])[:128]:
                if isinstance(item, dict):
                    move_mouse_relative(float(item.get("dx", 0)), float(item.get("dy", 0)), self.sensitivity)
        elif kind == "key":
            code = str(message.get("code", ""))
            down = bool(message.get("down"))
            self.set_key_state(code, down)
        elif kind == "mouse":
            button = str(message.get("button", ""))
            down = bool(message.get("down"))
            self.set_mouse_state(button, down)
        elif kind == "wheel":
            wheel(int(message.get("delta", 0)))
        elif kind == "release_all":
            self.release_all()
        else:
            raise ValueError(f"unsupported message type: {kind}")

    def set_key_state(self, code: str, down: bool) -> None:
        if down and code in self.keys_down:
            return
        if not down and code not in self.keys_down:
            return
        set_key(code, down)
        if down:
            self.keys_down.add(code)
        else:
            self.keys_down.discard(code)

    def set_mouse_state(self, button: str, down: bool) -> None:
        if down and button in self.mouse_down:
            return
        if not down and button not in self.mouse_down:
            return
        set_mouse_button(button, down)
        if down:
            self.mouse_down.add(button)
        else:
            self.mouse_down.discard(button)

    def release_all(self) -> None:
        for button in list(self.mouse_down):
            try:
                set_mouse_button(button, False)
            finally:
                self.mouse_down.discard(button)
        for code in list(self.keys_down):
            try:
                set_key(code, False)
            finally:
                self.keys_down.discard(code)


def get_lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def get_or_create_token(requested_token: str | None, reset_token: bool = False) -> str:
    if requested_token:
        TOKEN_FILE.write_text(requested_token, encoding="utf-8")
        return requested_token
    if not reset_token and TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if token:
            return token
    token = secrets.token_urlsafe(12)
    TOKEN_FILE.write_text(token, encoding="utf-8")
    return token


def no_cache_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
    }


def invalid_link_response(lan_ip: str, port: int) -> web.Response:
    body = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>FPS Controller Link Expired</title>
    <style>
      body {{
        margin: 0;
        min-height: 100vh;
        display: grid;
        place-items: center;
        font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        background: #0c0f14;
        color: #f6f7fb;
      }}
      main {{
        max-width: 560px;
        padding: 28px;
        line-height: 1.45;
      }}
      p {{
        color: #bac2cf;
      }}
      code {{
        color: #fff;
      }}
    </style>
  </head>
  <body>
    <main>
      <h1>FPS controller link expired</h1>
      <p>The token is missing or no longer matches the PC service.</p>
      <p>Use the exact URL printed in the PC window:</p>
      <p><code>http://{lan_ip}:{port}/?token=...</code></p>
    </main>
  </body>
</html>"""
    return web.Response(text=body, content_type="text/html", headers=no_cache_headers(), status=401)


async def index(request: web.Request) -> web.StreamResponse:
    app = request.app
    if request.query.get("token") != app["token"]:
        return invalid_link_response(app["lan_ip"], app["port"])
    return web.FileResponse(STATIC_DIR / "index.html", headers=no_cache_headers())


async def health(_: web.Request) -> web.Response:
    return web.json_response({"ok": True})


async def control(request: web.Request) -> web.WebSocketResponse:
    app = request.app
    if request.query.get("token") != app["token"]:
        raise web.HTTPUnauthorized(text="invalid token")

    ws = web.WebSocketResponse(heartbeat=20, max_msg_size=512 * 1024)
    await ws.prepare(request)
    session = InputSession(sensitivity=float(app["sensitivity"]))
    await ws.send_json({"type": "ready", "sensitivity": app["sensitivity"]})

    peer = request.remote or "unknown"
    print(f"[fps controller] connected: {peer}", flush=True)
    try:
        async for msg in ws:
            if msg.type != web.WSMsgType.TEXT:
                continue
            try:
                payload = json.loads(msg.data)
                session.handle(payload)
            except Exception as exc:
                print(f"[fps controller error] {exc}", flush=True)
                await ws.send_json({"type": "error", "message": str(exc)})
    finally:
        session.release_all()
        print(f"[fps controller] disconnected: {peer}", flush=True)
    return ws


def create_app(
    token: str,
    lan_ip: str | None = None,
    port: int | None = None,
    sensitivity: float = 1.0,
) -> web.Application:
    app = web.Application()
    app["token"] = token
    app["lan_ip"] = lan_ip or get_lan_ip()
    app["port"] = port or 8792
    app["sensitivity"] = sensitivity
    app.router.add_get("/", index)
    app.router.add_get("/health", health)
    app.router.add_get("/control", control)
    app.router.add_static("/static", STATIC_DIR)
    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local mobile FPS controller bridge.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8792)
    parser.add_argument("--token", default=None)
    parser.add_argument("--new-token", action="store_true", help="Generate and persist a new token.")
    parser.add_argument("--sensitivity", type=float, default=1.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    token = get_or_create_token(args.token, reset_token=args.new_token)
    lan_ip = get_lan_ip()
    app = create_app(token=token, lan_ip=lan_ip, port=args.port, sensitivity=args.sensitivity)
    print("Mobile FPS controller bridge is running.", flush=True)
    print(f"Open on mobile device: http://{lan_ip}:{args.port}/?token={token}", flush=True)
    print(f"Mouse sensitivity multiplier: {args.sensitivity}", flush=True)
    print("Close this service or the mobile page to release held inputs.", flush=True)
    try:
        web.run_app(app, host=args.host, port=args.port, print=None)
    except OSError as exc:
        print("", flush=True)
        print(f"Failed to start server on port {args.port}.", flush=True)
        print(f"Reason: {exc}", flush=True)
        print("If this port is already in use, close the old window or start with another port:", flush=True)
        print(f"  python server.py --port {args.port + 1}", flush=True)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
