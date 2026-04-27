import argparse
import asyncio
import contextlib
import ctypes
import ctypes.util
import json
import os
import re
import secrets
import socket
import ssl
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

from aiohttp import ClientSession, web


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
CERT_DIR = ROOT / "certs"
DEFAULT_CA_FILE = CERT_DIR / "local-ca.crt"
DEFAULT_CERT_FILE = CERT_DIR / "server.crt"
DEFAULT_KEY_FILE = CERT_DIR / "server.key"
ENV_FILE = ROOT / ".env"
DASHSCOPE_WS_URL = "wss://dashscope.aliyuncs.com/api-ws/v1/inference"
DASHSCOPE_MODEL = "paraformer-realtime-v2"
DEFAULT_DASHSCOPE_SAMPLE_RATE = 16000

VK_BACK = 0x08
VK_RETURN = 0x0D

APPLICATION_SERVICES = ctypes.CDLL(
    ctypes.util.find_library("ApplicationServices")
    or "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
)
CORE_FOUNDATION = ctypes.CDLL(
    ctypes.util.find_library("CoreFoundation")
    or "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
)

CGEventRef = ctypes.c_void_p
CGKeyCode = ctypes.c_uint16
UniChar = ctypes.c_uint16
kCGHIDEventTap = 0
MAC_KEY_RETURN = 36
MAC_KEY_DELETE = 51

APPLICATION_SERVICES.CGEventCreateKeyboardEvent.argtypes = (
    ctypes.c_void_p,
    CGKeyCode,
    ctypes.c_bool,
)
APPLICATION_SERVICES.CGEventCreateKeyboardEvent.restype = CGEventRef
APPLICATION_SERVICES.CGEventKeyboardSetUnicodeString.argtypes = (
    CGEventRef,
    ctypes.c_ulong,
    ctypes.POINTER(UniChar),
)
APPLICATION_SERVICES.CGEventPost.argtypes = (ctypes.c_uint32, CGEventRef)
APPLICATION_SERVICES.CGEventPost.restype = None
CORE_FOUNDATION.CFRelease.argtypes = (ctypes.c_void_p,)
CORE_FOUNDATION.CFRelease.restype = None


def _post_mac_key(key_code: int, is_down: bool) -> None:
    event = APPLICATION_SERVICES.CGEventCreateKeyboardEvent(None, key_code, is_down)
    if not event:
        raise RuntimeError("failed to create macOS keyboard event")
    try:
        APPLICATION_SERVICES.CGEventPost(kCGHIDEventTap, event)
    finally:
        CORE_FOUNDATION.CFRelease(event)


def _post_mac_unicode(code_unit: int, is_down: bool) -> None:
    event = APPLICATION_SERVICES.CGEventCreateKeyboardEvent(None, 0, is_down)
    if not event:
        raise RuntimeError("failed to create macOS unicode keyboard event")
    chars = (UniChar * 1)(code_unit)
    try:
        APPLICATION_SERVICES.CGEventKeyboardSetUnicodeString(event, 1, chars)
        APPLICATION_SERVICES.CGEventPost(kCGHIDEventTap, event)
    finally:
        CORE_FOUNDATION.CFRelease(event)


def press_key(vk: int) -> None:
    key_code = MAC_KEY_RETURN if vk == VK_RETURN else MAC_KEY_DELETE if vk == VK_BACK else vk
    _post_mac_key(key_code, True)
    _post_mac_key(key_code, False)


def type_text(text: str) -> None:
    data = text.encode("utf-16-le")
    for i in range(0, len(data), 2):
        code_unit = data[i] | (data[i + 1] << 8)
        if code_unit == 0x000A:
            press_key(VK_RETURN)
            continue
        if code_unit == 0x000D:
            continue
        _post_mac_unicode(code_unit, True)
        _post_mac_unicode(code_unit, False)


def backspace(count: int) -> None:
    for _ in range(max(0, min(count, 1000))):
        press_key(VK_BACK)


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
    return get_lan_ips()[0]


def get_lan_ips() -> list[str]:
    interface_ips: list[tuple[str, str]] = []
    current_interface = ""
    try:
        output = subprocess.check_output(["ifconfig"], text=True)
    except (OSError, subprocess.CalledProcessError):
        output = ""

    for line in output.splitlines():
        if line and not line.startswith(("\t", " ")):
            current_interface = line.split(":", 1)[0]
            continue
        match = re.search(r"\binet\s+(\d+\.\d+\.\d+\.\d+)\b", line)
        if not match:
            continue
        ip = match.group(1)
        if ip.startswith("127.") or ip.startswith("169.254."):
            continue
        interface_ips.append((current_interface, ip))

    preferred_prefixes = ("en", "bridge", "ap")
    preferred = [ip for name, ip in interface_ips if name.startswith(preferred_prefixes)]
    fallback = [ip for name, ip in interface_ips if not name.startswith(("lo", "utun", "gif", "stf"))]
    all_ips = preferred + fallback + [ip for _, ip in interface_ips]

    unique: list[str] = []
    for ip in all_ips:
        if ip not in unique:
            unique.append(ip)

    if unique:
        return unique

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return [s.getsockname()[0]]
    except OSError:
        return ["127.0.0.1"]


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


def parse_asr_sample_rate(value: str | None) -> int:
    if not value:
        return DEFAULT_DASHSCOPE_SAMPLE_RATE
    try:
        sample_rate = int(value)
    except ValueError:
        return DEFAULT_DASHSCOPE_SAMPLE_RATE
    if 8000 <= sample_rate <= 96000:
        return sample_rate
    return DEFAULT_DASHSCOPE_SAMPLE_RATE


def build_dashscope_run_task(task_id: str, sample_rate: int) -> dict[str, Any]:
    return {
        "header": {
            "action": "run-task",
            "task_id": task_id,
            "streaming": "duplex",
        },
        "payload": {
            "task_group": "audio",
            "task": "asr",
            "function": "recognition",
            "model": DASHSCOPE_MODEL,
            "parameters": {
                "format": "pcm",
                "sample_rate": sample_rate,
                "language_hints": ["zh"],
                "disfluency_removal_enabled": True,
                "punctuation_prediction_enabled": True,
                "inverse_text_normalization_enabled": True,
                "semantic_punctuation_enabled": False,
                "max_sentence_silence": 1200,
            },
            "input": {},
        },
    }


def build_dashscope_finish_task(task_id: str) -> dict[str, Any]:
    return {
        "header": {
            "action": "finish-task",
            "task_id": task_id,
            "streaming": "duplex",
        },
        "payload": {
            "input": {},
        },
    }


def extract_dashscope_sentence(message: dict[str, Any]) -> dict[str, Any] | None:
    try:
        sentence = message["payload"]["output"]["sentence"]
    except (KeyError, TypeError):
        return None
    text = sentence.get("text")
    if not isinstance(text, str) or sentence.get("heartbeat") is True:
        return None
    return {
        "text": text,
        "sentence_end": bool(sentence.get("sentence_end")),
        "begin_time": sentence.get("begin_time"),
        "end_time": sentence.get("end_time"),
    }


def read_local_env_value(name: str) -> str:
    if not ENV_FILE.exists():
        return ""
    try:
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    prefix = f"{name}="
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or not stripped.startswith(prefix):
            continue
        value = stripped[len(prefix) :].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        return value
    return ""


def get_dashscope_api_key() -> str:
    return os.environ.get("DASHSCOPE_API_KEY", "").strip() or read_local_env_value("DASHSCOPE_API_KEY").strip()


def build_ssl_context(cert_file: Path, key_file: Path) -> ssl.SSLContext:
    missing = [str(path) for path in (cert_file, key_file) if not path.exists()]
    if missing:
        joined = "\n  ".join(missing)
        raise FileNotFoundError(
            "HTTPS certificate files are missing. Run this first:\n"
            "  python3 scripts/setup_https.py\n"
            f"Missing:\n  {joined}"
        )
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(certfile=cert_file, keyfile=key_file)
    return context


def cert_help_html(ca_file: Path) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>安装本地 HTTPS 证书</title>
    <style>
      body {{ margin: 0; padding: 24px; font: 16px/1.55 system-ui, sans-serif; color: #211a12; background: #fffaf1; }}
      main {{ max-width: 760px; margin: 0 auto; }}
      a, code {{ color: #0f6b5f; }}
      a.button {{ display: inline-block; margin: 12px 0; padding: 12px 16px; border-radius: 10px; color: #fffaf1; background: #0f6b5f; text-decoration: none; font-weight: 700; }}
      li {{ margin: 8px 0; }}
    </style>
  </head>
  <body>
    <main>
      <h1>安装本地 HTTPS 证书</h1>
      <p>这个证书只用于让手机信任当前 Mac 的局域网 HTTPS 服务，从而允许网页调用麦克风。</p>
      <p><a class="button" href="/cert/ca.crt">下载 CA 证书</a></p>
      <h2>iPhone / iPad</h2>
      <ol>
        <li>点击上面的下载按钮，允许下载描述文件。</li>
        <li>打开“设置”，进入“已下载描述文件”，安装证书。</li>
        <li>进入“设置 -> 通用 -> 关于本机 -> 证书信任设置”，开启 <code>Voice from Phone Local CA</code> 的完全信任。</li>
        <li>重新打开本服务的 HTTPS 地址。</li>
      </ol>
      <h2>Android</h2>
      <ol>
        <li>点击上面的下载按钮保存证书。</li>
        <li>在系统设置里搜索“安装证书”或“CA 证书”，选择下载的证书安装。</li>
        <li>重新打开本服务的 HTTPS 地址。</li>
      </ol>
      <p>当前服务端 CA 文件：<code>{ca_file.name}</code></p>
    </main>
  </body>
</html>"""


def create_app(token: str, ca_file: Path = DEFAULT_CA_FILE) -> web.Application:
    app = web.Application()
    session = TextSession()

    async def index(request: web.Request) -> web.FileResponse:
        return web.FileResponse(STATIC_DIR / "index.html")

    async def health(_: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    async def download_ca(_: web.Request) -> web.FileResponse:
        if not ca_file.exists():
            raise web.HTTPNotFound(text="CA certificate not found. Run python3 scripts/setup_https.py first.")
        return web.FileResponse(
            ca_file,
            headers={
                "Content-Disposition": 'attachment; filename="voice-from-phone-local-ca.crt"',
            },
        )

    async def cert_help(_: web.Request) -> web.Response:
        return web.Response(text=cert_help_html(ca_file), content_type="text/html")

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

    async def asr_websocket_handler(request: web.Request) -> web.WebSocketResponse:
        if request.query.get("token") != token:
            raise web.HTTPUnauthorized(text="invalid token")

        client_ws = web.WebSocketResponse(heartbeat=20, max_msg_size=8 * 1024 * 1024)
        await client_ws.prepare(request)

        api_key = get_dashscope_api_key()
        if not api_key:
            await client_ws.send_json(
                {
                    "type": "asr_error",
                    "message": "DASHSCOPE_API_KEY is not set on the Mac server.",
                }
            )
            await client_ws.close()
            return client_ws

        sample_rate = parse_asr_sample_rate(request.query.get("sample_rate"))
        task_id = uuid.uuid4().hex
        started = asyncio.Event()
        finished = asyncio.Event()
        committed_text = ""

        async with ClientSession() as http:
            try:
                dash_ws = await http.ws_connect(
                    DASHSCOPE_WS_URL,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "user-agent": "voice-from-phone-macos/1.0",
                    },
                    heartbeat=20,
                    max_msg_size=8 * 1024 * 1024,
                )
            except Exception as exc:
                await client_ws.send_json({"type": "asr_error", "message": f"DashScope connect failed: {exc}"})
                await client_ws.close()
                return client_ws

            await dash_ws.send_json(build_dashscope_run_task(task_id, sample_rate))
            await client_ws.send_json({"type": "asr_connecting"})
            session.reset()

            async def receive_dashscope() -> None:
                nonlocal committed_text
                async for dash_msg in dash_ws:
                    if dash_msg.type != web.WSMsgType.TEXT:
                        continue
                    try:
                        payload = json.loads(dash_msg.data)
                    except json.JSONDecodeError:
                        continue
                    header = payload.get("header") or {}
                    event = header.get("event")
                    if event == "task-started":
                        print(f"[asr] task started: {task_id}", flush=True)
                        started.set()
                        await client_ws.send_json({"type": "asr_started"})
                    elif event == "result-generated":
                        sentence = extract_dashscope_sentence(payload)
                        if sentence is None:
                            continue
                        full_text = committed_text + sentence["text"]
                        print(f"[asr] {full_text!r}", flush=True)
                        if sentence["sentence_end"]:
                            committed_text = full_text
                            session.replace(committed_text[:5000])
                        await client_ws.send_json(
                            {
                                "type": "asr_result",
                                "text": committed_text,
                                "partial": sentence["text"],
                                "sentence_end": sentence["sentence_end"],
                            }
                        )
                    elif event == "task-finished":
                        print(f"[asr] task finished: {task_id}", flush=True)
                        finished.set()
                        await client_ws.send_json({"type": "asr_finished"})
                        break
                    elif event == "task-failed":
                        error_message = header.get("error_message") or "DashScope task failed"
                        print(f"[asr error] {error_message}", flush=True)
                        finished.set()
                        await client_ws.send_json({"type": "asr_error", "message": error_message})
                        break

            dash_reader = asyncio.create_task(receive_dashscope())
            finish_sent = False
            try:
                async for msg in client_ws:
                    if msg.type == web.WSMsgType.TEXT:
                        try:
                            payload = json.loads(msg.data)
                        except json.JSONDecodeError:
                            continue
                        if payload.get("type") == "finish_asr":
                            if started.is_set() and not finish_sent:
                                await dash_ws.send_json(build_dashscope_finish_task(task_id))
                                finish_sent = True
                            break
                    elif msg.type == web.WSMsgType.BINARY:
                        if not started.is_set():
                            try:
                                await asyncio.wait_for(started.wait(), timeout=5)
                            except asyncio.TimeoutError:
                                await client_ws.send_json({"type": "asr_error", "message": "DashScope task did not start."})
                                break
                        if dash_ws.closed:
                            break
                        await dash_ws.send_bytes(msg.data)
            finally:
                if started.is_set() and not finish_sent and not dash_ws.closed:
                    with contextlib.suppress(Exception):
                        await dash_ws.send_json(build_dashscope_finish_task(task_id))
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(finished.wait(), timeout=3)
                dash_reader.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await dash_reader
                await dash_ws.close()

        return client_ws

    app.router.add_get("/", index)
    app.router.add_get("/health", health)
    app.router.add_get("/cert/ca.crt", download_ca)
    app.router.add_get("/cert/help", cert_help)
    app.router.add_get("/ws", websocket_handler)
    app.router.add_get("/asr_ws", asr_websocket_handler)
    app.router.add_static("/static", STATIC_DIR)
    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phone realtime input bridge for macOS.")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host, default: 0.0.0.0")
    parser.add_argument("--port", type=int, default=8787, help="Bind port, default: 8787")
    parser.add_argument("--token", default=None, help="Session token. Defaults to a random token.")
    parser.add_argument("--test-text", default=None, help="Type text into the current Mac focus after a countdown, then exit.")
    parser.add_argument("--https", action="store_true", help="Serve over HTTPS using local certificates.")
    parser.add_argument("--cert-file", default=str(DEFAULT_CERT_FILE), help="HTTPS server certificate path.")
    parser.add_argument("--key-file", default=str(DEFAULT_KEY_FILE), help="HTTPS server private key path.")
    parser.add_argument("--ca-file", default=str(DEFAULT_CA_FILE), help="CA certificate download path.")
    return parser.parse_args()


def main() -> None:
    if sys.platform != "darwin":
        raise SystemExit("This macOS version injects text with CoreGraphics and must run on macOS.")

    args = parse_args()
    if args.test_text is not None:
        print("Focus the target input box within 3 seconds...", flush=True)
        import time

        time.sleep(3)
        type_text(args.test_text)
        print("Test text sent.", flush=True)
        return

    token = args.token or secrets.token_urlsafe(12)
    ca_file = Path(args.ca_file).expanduser().resolve()
    cert_file = Path(args.cert_file).expanduser().resolve()
    key_file = Path(args.key_file).expanduser().resolve()
    ssl_context = None
    scheme = "http"
    if args.https:
        try:
            ssl_context = build_ssl_context(cert_file, key_file)
        except FileNotFoundError as exc:
            raise SystemExit(str(exc))
        scheme = "https"

    app = create_app(token, ca_file=ca_file)

    lan_ip = get_lan_ip()
    print("Phone realtime input bridge for macOS is running.")
    print(f"Open on phone: {scheme}://{lan_ip}:{args.port}/?token={token}")
    print(f"Certificate help: {scheme}://{lan_ip}:{args.port}/cert/help")
    print("Keep the target app focused on this Mac; phone input will be typed there.")
    print("macOS may require Accessibility and Input Monitoring permission for Terminal or Python.")
    if get_dashscope_api_key():
        print("Aliyun Paraformer realtime ASR is enabled.")
    else:
        print("Set DASHSCOPE_API_KEY or macOS_version/.env to enable the microphone ASR button on the phone page.")
    web.run_app(app, host=args.host, port=args.port, ssl_context=ssl_context, print=None)


if __name__ == "__main__":
    main()
