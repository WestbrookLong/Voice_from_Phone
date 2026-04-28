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
TOKEN_FILE = ROOT / ".whiteboard_token"

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000
INPUT_MOUSE = 0
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79
ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

if sys.platform != "win32":
    raise SystemExit("This server injects Windows mouse input and must run on Windows.")

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


class INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT)]


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


def monitor_rect(monitor_id: int) -> dict[str, int]:
    try:
        import mss

        with mss.mss() as sct:
            index = max(1, min(monitor_id, len(sct.monitors) - 1))
            monitor = dict(sct.monitors[index])
            return {
                "left": int(monitor["left"]),
                "top": int(monitor["top"]),
                "width": int(monitor["width"]),
                "height": int(monitor["height"]),
            }
    except Exception:
        return virtual_screen_rect()


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


def clamp_ratio(value: Any) -> float:
    return max(0.0, min(1.0, float(value)))


def inject_pointer_event(event: dict[str, Any], monitor: dict[str, int]) -> None:
    action = event.get("action")
    x_ratio = clamp_ratio(event.get("x"))
    y_ratio = clamp_ratio(event.get("y"))
    x = int(monitor["left"] + x_ratio * max(1, monitor["width"] - 1))
    y = int(monitor["top"] + y_ratio * max(1, monitor["height"] - 1))

    if action == "down":
        move_mouse_to_screen_point(x, y)
        left_mouse_down()
    elif action == "move":
        move_mouse_to_screen_point(x, y)
    elif action == "up":
        move_mouse_to_screen_point(x, y)
        left_mouse_up()
    else:
        raise ValueError(f"unsupported pointer action: {action}")


def parse_pointer_message(raw: str) -> list[dict[str, Any]]:
    payload = json.loads(raw)
    if payload.get("type") == "pointer":
        return [payload]
    if payload.get("type") == "pointer_batch":
        events = payload.get("events")
        if not isinstance(events, list):
            raise ValueError("pointer_batch.events must be a list")
        return [event for event in events[:256] if isinstance(event, dict)]
    raise ValueError("unsupported message type")


def no_cache_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
    }


def no_cache_file(path: Path) -> web.FileResponse:
    return web.FileResponse(
        path,
        headers=no_cache_headers(),
    )


def invalid_link_response(lan_ip: str, port: int) -> web.Response:
    body = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Whiteboard Link Expired</title>
    <style>
      body {{
        margin: 0;
        min-height: 100vh;
        display: grid;
        place-items: center;
        font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        background: #fff;
        color: #111;
      }}
      main {{
        max-width: 560px;
        padding: 28px;
        line-height: 1.45;
      }}
      h1 {{
        margin: 0 0 12px;
        font-size: 24px;
      }}
      p {{
        margin: 8px 0;
        color: #444;
      }}
      code {{
        color: #111;
      }}
    </style>
  </head>
  <body>
    <main>
      <h1>Whiteboard link expired</h1>
      <p>This page opened, but its token is missing or no longer matches the PC service.</p>
      <p>Use the exact URL printed in the PC window. It should look like:</p>
      <p><code>http://{lan_ip}:{port}/?token=...</code></p>
      <p>If the PC window was already open before the latest update, close it and start <code>start_whiteboard.bat</code> again.</p>
    </main>
  </body>
</html>"""
    return web.Response(text=body, content_type="text/html", headers=no_cache_headers(), status=401)


async def index(request: web.Request) -> web.StreamResponse:
    app = request.app
    if request.query.get("token") != app["token"]:
        return invalid_link_response(app["lan_ip"], app["port"])
    return no_cache_file(STATIC_DIR / "index.html")


async def health(_: web.Request) -> web.Response:
    return web.json_response({"ok": True})


async def pointer(request: web.Request) -> web.WebSocketResponse:
    app = request.app
    if request.query.get("token") != app["token"]:
        raise web.HTTPUnauthorized(text="invalid token")

    ws = web.WebSocketResponse(heartbeat=20, max_msg_size=2 * 1024 * 1024)
    await ws.prepare(request)
    monitor = app["monitor_rect"]
    await ws.send_json({"type": "ready", "monitor": monitor})

    peer = request.remote or "unknown"
    mouse_is_down = False
    print(f"[whiteboard pointer] connected: {peer}", flush=True)
    try:
        async for msg in ws:
            if msg.type != web.WSMsgType.TEXT:
                continue
            try:
                events = parse_pointer_message(msg.data)
                for event in events:
                    action = event.get("action")
                    if action == "down" and mouse_is_down:
                        left_mouse_up()
                        mouse_is_down = False
                    inject_pointer_event(event, monitor)
                    if action == "down":
                        mouse_is_down = True
                    elif action == "up":
                        mouse_is_down = False
            except Exception as exc:
                print(f"[whiteboard pointer error] {exc}", flush=True)
                await ws.send_json({"type": "error", "message": str(exc)})
    finally:
        if mouse_is_down:
            try:
                left_mouse_up()
            except Exception as exc:
                print(f"[whiteboard pointer cleanup error] {exc}", flush=True)
        print(f"[whiteboard pointer] disconnected: {peer}", flush=True)
    return ws


def create_app(token: str, monitor_id: int, lan_ip: str | None = None, port: int | None = None) -> web.Application:
    app = web.Application()
    app["token"] = token
    app["monitor_rect"] = monitor_rect(monitor_id)
    app["lan_ip"] = lan_ip or get_lan_ip()
    app["port"] = port or 8791
    app.router.add_get("/", index)
    app.router.add_get("/health", health)
    app.router.add_get("/pointer", pointer)
    app.router.add_static("/static", STATIC_DIR)
    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local iPad whiteboard to Windows mouse bridge.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8791)
    parser.add_argument("--token", default=None)
    parser.add_argument("--new-token", action="store_true", help="Generate and persist a new token.")
    parser.add_argument("--monitor", type=int, default=1)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    token = get_or_create_token(args.token, reset_token=args.new_token)
    app = create_app(token=token, monitor_id=args.monitor, lan_ip=get_lan_ip(), port=args.port)
    lan_ip = get_lan_ip()
    print("iPad whiteboard bridge is running.", flush=True)
    print(f"Open on iPad: http://{lan_ip}:{args.port}/?token={token}", flush=True)
    print(f"Mapping target: monitor={args.monitor}, rect={app['monitor_rect']}", flush=True)
    print("Switch tools on the PC app manually; this page only maps pointer strokes.", flush=True)
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
