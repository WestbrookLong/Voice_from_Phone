import argparse
import asyncio
import ctypes
import json
import secrets
import socket
import sys
from ctypes import wintypes
from io import BytesIO
from pathlib import Path
from typing import Any

from aiohttp import web
from PIL import Image, ImageDraw


def app_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


ROOT = app_root()
STATIC_DIR = ROOT / "static"

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
INPUT_KEYBOARD = 1
INPUT_MOUSE = 0
INPUT_HARDWARE = 2

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000
WHEEL_DELTA = 120

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

VK_BACK = 0x08
VK_TAB = 0x09
VK_RETURN = 0x0D
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_ESCAPE = 0x1B
VK_SPACE = 0x20
VK_PRIOR = 0x21
VK_NEXT = 0x22
VK_END = 0x23
VK_HOME = 0x24
VK_LEFT = 0x25
VK_UP = 0x26
VK_RIGHT = 0x27
VK_DOWN = 0x28
VK_DELETE = 0x2E
VK_LWIN = 0x5B
VK_RWIN = 0x5C

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


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


USER32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
USER32.SendInput.restype = wintypes.UINT
USER32.GetSystemMetrics.argtypes = (ctypes.c_int,)
USER32.GetSystemMetrics.restype = ctypes.c_int
USER32.GetCursorPos.argtypes = (ctypes.POINTER(POINT),)
USER32.GetCursorPos.restype = wintypes.BOOL

KEY_CODES: dict[str, int] = {
    "Backspace": VK_BACK,
    "Tab": VK_TAB,
    "Enter": VK_RETURN,
    "ShiftLeft": VK_SHIFT,
    "ShiftRight": VK_SHIFT,
    "ControlLeft": VK_CONTROL,
    "ControlRight": VK_CONTROL,
    "AltLeft": VK_MENU,
    "AltRight": VK_MENU,
    "Escape": VK_ESCAPE,
    "Space": VK_SPACE,
    "PageUp": VK_PRIOR,
    "PageDown": VK_NEXT,
    "End": VK_END,
    "Home": VK_HOME,
    "ArrowLeft": VK_LEFT,
    "ArrowUp": VK_UP,
    "ArrowRight": VK_RIGHT,
    "ArrowDown": VK_DOWN,
    "Delete": VK_DELETE,
    "MetaLeft": VK_LWIN,
    "MetaRight": VK_RWIN,
    "WinLeft": VK_LWIN,
    "WinRight": VK_RWIN,
}

for index, letter in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ", start=0x41):
    KEY_CODES[f"Key{letter}"] = index
for digit in range(10):
    KEY_CODES[f"Digit{digit}"] = 0x30 + digit

US_CHAR_KEYS: dict[str, tuple[int, bool]] = {
    " ": (VK_SPACE, False),
    "\n": (VK_RETURN, False),
    "\r": (VK_RETURN, False),
    "\t": (VK_TAB, False),
    "`": (0xC0, False),
    "~": (0xC0, True),
    "-": (0xBD, False),
    "_": (0xBD, True),
    "=": (0xBB, False),
    "+": (0xBB, True),
    "[": (0xDB, False),
    "{": (0xDB, True),
    "]": (0xDD, False),
    "}": (0xDD, True),
    "\\": (0xDC, False),
    "|": (0xDC, True),
    ";": (0xBA, False),
    ":": (0xBA, True),
    "'": (0xDE, False),
    '"': (0xDE, True),
    ",": (0xBC, False),
    "<": (0xBC, True),
    ".": (0xBE, False),
    ">": (0xBE, True),
    "/": (0xBF, False),
    "?": (0xBF, True),
    "!": (0x31, True),
    "@": (0x32, True),
    "#": (0x33, True),
    "$": (0x34, True),
    "%": (0x35, True),
    "^": (0x36, True),
    "&": (0x37, True),
    "*": (0x38, True),
    "(": (0x39, True),
    ")": (0x30, True),
}

MOUSE_BUTTON_FLAGS = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}


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


def key_down(vk: int) -> None:
    _send_keyboard_input(vk=vk)


def key_up(vk: int) -> None:
    _send_keyboard_input(vk=vk, flags=KEYEVENTF_KEYUP)


def press_key(vk: int) -> None:
    key_down(vk)
    key_up(vk)


def set_key_by_code(code: str, down: bool) -> None:
    vk = KEY_CODES.get(code)
    if vk is None:
        raise ValueError(f"unsupported key code: {code}")
    if down:
        key_down(vk)
    else:
        key_up(vk)


def tap_character(character: str) -> None:
    if len(character) != 1:
        return
    if "a" <= character <= "z":
        press_key(ord(character.upper()))
        return
    if "A" <= character <= "Z":
        key_down(VK_SHIFT)
        try:
            press_key(ord(character))
        finally:
            key_up(VK_SHIFT)
        return
    if "0" <= character <= "9":
        press_key(ord(character))
        return
    mapped = US_CHAR_KEYS.get(character)
    if mapped is None:
        type_text(character)
        return
    vk, needs_shift = mapped
    if needs_shift:
        key_down(VK_SHIFT)
    try:
        press_key(vk)
    finally:
        if needs_shift:
            key_up(VK_SHIFT)


def tap_keyboard_text(text: str) -> None:
    for character in text[:256]:
        tap_character(character)


def type_text(text: str) -> None:
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


def set_mouse_button(button: str, down: bool) -> None:
    if button not in MOUSE_BUTTON_FLAGS:
        raise ValueError(f"unsupported mouse button: {button}")
    down_flag, up_flag = MOUSE_BUTTON_FLAGS[button]
    _send_mouse_input(flags=down_flag if down else up_flag)


def move_mouse_relative(dx: float, dy: float, sensitivity: float = 1.0) -> None:
    scaled_dx = int(round(dx * sensitivity))
    scaled_dy = int(round(dy * sensitivity))
    if scaled_dx == 0 and scaled_dy == 0:
        return
    _send_mouse_input(dx=scaled_dx, dy=scaled_dy, flags=MOUSEEVENTF_MOVE)


def mouse_wheel(delta: int) -> None:
    _send_mouse_input(dx=0, dy=0, flags=MOUSEEVENTF_WHEEL, mouse_data=delta)


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


def capture_jpeg(monitor_id: int, quality: int) -> tuple[dict[str, int], bytes]:
    import mss

    with mss.mss() as sct:
        monitor_index = max(1, min(monitor_id, len(sct.monitors) - 1))
        monitor = dict(sct.monitors[monitor_index])
        shot = sct.grab(monitor)
        image = Image.frombytes("RGB", shot.size, shot.rgb)
        draw_cursor_marker(image, monitor)
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=quality, optimize=False)
        return monitor, buffer.getvalue()


def cursor_position() -> tuple[int, int] | None:
    point = POINT()
    if not USER32.GetCursorPos(ctypes.byref(point)):
        return None
    return point.x, point.y


def draw_cursor_marker(image: Image.Image, monitor: dict[str, int]) -> None:
    position = cursor_position()
    if position is None:
        return
    cursor_x, cursor_y = position
    local_x = cursor_x - int(monitor["left"])
    local_y = cursor_y - int(monitor["top"])
    if local_x < 0 or local_y < 0 or local_x >= image.width or local_y >= image.height:
        return

    draw = ImageDraw.Draw(image)
    arrow = [
        (local_x, local_y),
        (local_x, local_y + 31),
        (local_x + 8, local_y + 23),
        (local_x + 13, local_y + 36),
        (local_x + 19, local_y + 34),
        (local_x + 14, local_y + 21),
        (local_x + 25, local_y + 21),
    ]
    draw.polygon(arrow, fill=(0, 0, 0))
    inner = [
        (local_x + 2, local_y + 5),
        (local_x + 2, local_y + 26),
        (local_x + 8, local_y + 19),
        (local_x + 14, local_y + 32),
        (local_x + 16, local_y + 31),
        (local_x + 11, local_y + 18),
        (local_x + 20, local_y + 18),
    ]
    draw.polygon(inner, fill=(255, 255, 255))


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


class InputSession:
    def __init__(self, sensitivity: float = 1.0) -> None:
        self.sensitivity = sensitivity
        self.keys_down: set[str] = set()
        self.mouse_down: set[str] = set()

    def handle(self, payload: dict[str, Any]) -> None:
        message_type = payload.get("type")
        if message_type == "look":
            move_mouse_relative(float(payload.get("dx", 0)), float(payload.get("dy", 0)), self.sensitivity)
        elif message_type == "key":
            self.set_key_state(str(payload.get("code", "")), bool(payload.get("down")))
        elif message_type == "tap_key":
            code = str(payload.get("code", ""))
            set_key_by_code(code, True)
            set_key_by_code(code, False)
        elif message_type == "keyboard_text":
            text = payload.get("text", "")
            if not isinstance(text, str):
                raise ValueError("keyboard_text.text must be a string")
            tap_keyboard_text(text)
        elif message_type == "ime_text":
            text = payload.get("text", "")
            if not isinstance(text, str):
                raise ValueError("ime_text.text must be a string")
            type_text(text[:5000])
        elif message_type == "mouse":
            self.set_mouse_state(str(payload.get("button", "")), bool(payload.get("down")))
        elif message_type == "wheel":
            mouse_wheel(max(-1200, min(1200, int(payload.get("delta", 0)))))
        elif message_type == "release_all":
            self.release_all()
        else:
            raise ValueError(f"unsupported control message type: {message_type}")

    def set_key_state(self, code: str, down: bool) -> None:
        if down and code in self.keys_down:
            return
        if not down and code not in self.keys_down:
            return
        set_key_by_code(code, down)
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
                set_key_by_code(code, False)
            finally:
                self.keys_down.discard(code)


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


def create_app(token: str, sensitivity: float = 1.0) -> web.Application:
    app = web.Application()
    session = TextSession()

    def html_response(path: Path) -> web.FileResponse:
        return web.FileResponse(
            path,
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )

    async def index(request: web.Request) -> web.FileResponse:
        if request.query.get("token") != token:
            raise web.HTTPUnauthorized(text="invalid token")
        return html_response(STATIC_DIR / "index.html")

    async def tablet(request: web.Request) -> web.FileResponse:
        if request.query.get("token") != token:
            raise web.HTTPUnauthorized(text="invalid token")
        return html_response(STATIC_DIR / "tablet.html")

    async def health(_: web.Request) -> web.Response:
        return web.json_response({"ok": True})

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
                    await ws.send_json({"type": "screen_meta", "monitor": monitor, "fps": fps, "quality": quality})
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
                x_ratio = max(0.0, min(1.0, float(payload.get("x"))))
                y_ratio = max(0.0, min(1.0, float(payload.get("y"))))
                x = int(monitor["left"] + x_ratio * max(1, monitor["width"] - 1))
                y = int(monitor["top"] + y_ratio * max(1, monitor["height"] - 1))
                action = payload.get("action")

                if action == "wheel":
                    delta = int(payload.get("delta", 0))
                    if delta:
                        mouse_wheel(max(-1200, min(1200, delta)))
                elif action == "down":
                    move_mouse_to_screen_point(x, y)
                    set_mouse_button("left", True)
                elif action == "up":
                    move_mouse_to_screen_point(x, y)
                    set_mouse_button("left", False)
                elif action == "move":
                    move_mouse_to_screen_point(x, y)
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
                    session.replace(text[:5000])
                elif payload.get("type") == "reset_session":
                    session.reset()
                else:
                    ops = validate_ops(payload)
                    for op in ops:
                        if op["type"] == "insert":
                            type_text(op["text"])
                        elif op["type"] == "enter":
                            press_key(VK_RETURN)
                        elif op["type"] == "backspace":
                            backspace(op["count"])
                await ws.send_json({"type": "ack", "seq": payload.get("seq")})
            except Exception as exc:
                print(f"[error] {exc}", flush=True)
                await ws.send_json({"type": "error", "message": str(exc)})

        print(f"[ws] disconnected: {peer}", flush=True)
        return ws

    async def control_handler(request: web.Request) -> web.WebSocketResponse:
        if request.query.get("token") != token:
            raise web.HTTPUnauthorized(text="invalid token")

        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=512 * 1024)
        await ws.prepare(request)
        input_session = InputSession(sensitivity=sensitivity)
        peer = request.remote or "unknown"
        print(f"[control] connected: {peer}", flush=True)
        await ws.send_json({"type": "ready", "sensitivity": sensitivity})

        try:
            async for msg in ws:
                if msg.type != web.WSMsgType.TEXT:
                    continue
                try:
                    payload = json.loads(msg.data)
                    if payload.get("token") != token:
                        raise ValueError("invalid token")
                    input_session.handle(payload)
                except Exception as exc:
                    print(f"[control error] {exc}", flush=True)
                    await ws.send_json({"type": "error", "message": str(exc)})
        finally:
            input_session.release_all()
            print(f"[control] disconnected: {peer}", flush=True)
        return ws

    app.router.add_get("/", index)
    app.router.add_get("/tablet", tablet)
    app.router.add_get("/health", health)
    app.router.add_get("/ws", websocket_handler)
    app.router.add_get("/screen", screen_handler)
    app.router.add_get("/pointer", pointer_handler)
    app.router.add_get("/control", control_handler)
    app.router.add_static("/static", STATIC_DIR)
    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mobile computer bridge for Windows.")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host, default: 0.0.0.0")
    parser.add_argument("--port", type=int, default=8788, help="Bind port, default: 8788")
    parser.add_argument("--token", default=None, help="Session token. Defaults to a random token.")
    parser.add_argument("--sensitivity", type=float, default=1.0, help="Relative mouse joystick sensitivity.")
    parser.add_argument("--test-text", default=None, help="Type text into the current Windows focus after a countdown, then exit.")
    return parser.parse_args()


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("This program injects input with Windows SendInput and must run on Windows.")

    args = parse_args()
    if args.test_text is not None:
        print("Focus the target input box within 3 seconds...", flush=True)
        import time

        time.sleep(3)
        type_text(args.test_text)
        print("Test text sent.", flush=True)
        return

    token = args.token or secrets.token_urlsafe(12)
    app = create_app(token, sensitivity=args.sensitivity)

    lan_ip = get_lan_ip()
    print("Mobile computer bridge is running.")
    print(f"Open on phone:  http://{lan_ip}:{args.port}/?token={token}")
    print(f"Open on iPad:   http://{lan_ip}:{args.port}/tablet?token={token}")
    print("Keep the target app focused on this PC; phone controls will be injected there.")
    web.run_app(app, host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
