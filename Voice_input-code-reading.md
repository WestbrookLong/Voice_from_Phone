# Voice_input Code Reading Report

## Repository Summary

`Voice_input` 是一个局域网内的手机到 Windows 光标输入桥接工具。用户在手机网页或 Flutter App 中输入文字，或使用手机输入法语音转文字，电脑端把这些文本变化实时注入到当前 Windows 光标位置。项目还扩展了一个移动端远程模式：移动端浏览器显示电脑屏幕，并把触控/Apple Pencil 动作映射为 Windows 鼠标事件。

从 `start_desktop_client.bat` 进入的主运行形态是 Windows 桌面客户端：批处理脚本启动 `desktop_client.py`，桌面 UI 生成 token、端口、URL 和二维码，然后在后台线程启动 `server.py` 中的 aiohttp 服务。服务端同时提供静态网页、WebSocket 文本同步、屏幕 JPEG 推流、指针事件注入和健康检查。

## Reading Context

- Source: local checkout at `D:\Users\WESTBROOK\Projects\Voice_input`
- Git branch: `main`
- Git commit: `6d33d5334f9a436a033521039a78dda18a2d7411`
- Primary runtime: Python 3 on Windows
- Main files read:
  - `start_desktop_client.bat`
  - `desktop_client.py`
  - `server.py`
  - `static/index.html`
  - `static/tablet.html`
  - `mobile_app/lib/main.dart`
  - `requirements.txt`
  - `VoiceInput.spec`
  - `PACKAGING.md`

## Architecture Overview

The main architecture has four layers:

1. Desktop launcher and control UI

`start_desktop_client.bat` changes the working directory to the repository folder and runs `python desktop_client.py`. `desktop_client.py` is a Tkinter application. It owns the user-facing Windows desktop window, exposes port/token controls, builds two URLs, generates QR codes, and starts/stops the server thread.

2. Local aiohttp server

`server.py` defines `create_app(token)`, which returns a single aiohttp application. It registers:

- `GET /` for the phone text input web page.
- `GET /tablet` for the mobile remote page.
- `GET /health` for a JSON health check.
- `GET /ws` for text input WebSocket messages.
- `GET /screen` for binary JPEG screen frames.
- `GET /pointer` for pointer/mouse WebSocket messages.
- `/static` for static assets.

3. Windows input injection

The server uses `ctypes` to call Win32 `user32.SendInput`. Keyboard injection is done with Unicode key events, while pointer injection uses absolute virtual desktop mouse events plus left button and wheel events.

4. Remote clients

`static/index.html` is the no-install phone web client. It opens `/ws`, sends full text state as `sync_text`, and sends `reset_session` when the local textbox is cleared.

`mobile_app/lib/main.dart` implements a Flutter Android client with the same `/ws` protocol, plus QR scanning through `mobile_scanner`.

`static/tablet.html` is a browser-based mobile remote client. It opens three WebSockets: `/screen` for display frames, `/pointer` for mouse movement/click/wheel injection, and `/ws` for optional keyboard text input.

## Main Execution Path

The Windows desktop path starts in `start_desktop_client.bat`:

```bat
@echo off
cd /d "%~dp0"
python desktop_client.py
```

`desktop_client.py` then constructs `DesktopClient`, a `tk.Tk` window. On startup it:

- detects the LAN IP with `get_lan_ip()`;
- generates a random token with `secrets.token_urlsafe(12)`;
- defaults the port to `8787`;
- builds a normal input URL and a tablet URL;
- renders a QR code using `qrcode` and `PIL.ImageTk`.

When the user clicks "启动服务", `DesktopClient._start_server()` validates the port and token, creates `BridgeServerThread("0.0.0.0", port, token, events)`, and starts it. `BridgeServerThread` creates an asyncio loop in a daemon thread, calls `create_app(token)`, wraps it with `web.AppRunner`, and starts a `web.TCPSite`.

Once a phone client connects:

- normal text input goes to `ws://<host>:<port>/ws?token=<token>`;
- Mobile remote display frames come from `ws://<host>:<port>/screen?token=<token>`;
- Mobile remote pointer input goes to `ws://<host>:<port>/pointer?token=<token>`.

Each WebSocket endpoint validates the URL token. The text and pointer handlers also validate the token in the JSON message body.

## Core Algorithm Breakdown

The core value of the project is not speech recognition. Speech recognition is delegated to the phone's system or third-party input method. The project synchronizes the phone text field's current state into Windows.

For text injection, `server.py` keeps one `TextSession` object inside `create_app(token)`. The important method is `TextSession.replace(new_text)`.

The algorithm is:

1. Keep the previous text sent by the current phone session as `self.text`.
2. When new full text arrives through `sync_text`, compute the longest common prefix of old and new text.
3. Delete the old suffix after that prefix with Backspace.
4. Type the new suffix after that prefix with Unicode `SendInput`.
5. Store the new text as the session state.

This design handles both normal streaming append and later voice-input corrections. If the old text is `今天下午三点凯会` and the phone later corrects it to `今天下午三点开会`, the common prefix is `今天下午三点`; the server backspaces two characters and types `开会`.

The main invariant is that the Windows caret is still at the end of the text injected during this session. If the user moves the caret in the target app, the Backspace-based correction can affect the wrong location.

For Unicode text, `type_text()` encodes text as UTF-16LE and sends each UTF-16 code unit through `KEYEVENTF_UNICODE`, with `\n` mapped to Enter. This avoids relying on the Windows IME or the clipboard.

For mobile remote mode, the core loop is split:

- `capture_jpeg()` uses `mss` to capture a monitor and Pillow to JPEG-encode it.
- `/screen` sends a `screen_meta` JSON message when monitor metadata changes, then sends JPEG bytes at a bounded FPS.
- `tablet.html` draws frames into a canvas, computes the image rectangle, and converts pointer coordinates into normalized `x/y` ratios.
- `/pointer` maps those ratios back to Windows virtual-screen coordinates and injects absolute mouse movement, left down/up, or wheel deltas.

## Current Implemented Features

- Windows desktop client with Tkinter.
- Start/stop controls for the local bridge server.
- Random session token and editable port.
- Phone text input URL and mobile remote URL.
- QR code generation for both URLs.
- Phone web client through `static/index.html`.
- Flutter Android client in `mobile_app/`, including QR scan connection.
- Full-text `sync_text` protocol for voice input correction.
- `reset_session` protocol that clears server-side session state without deleting already injected computer text.
- Legacy `ops` protocol support for insert/enter/backspace operations.
- Unicode text injection into the current Windows focus.
- Enter and Backspace injection.
- Mobile remote page with screen streaming, pointer down/move/up, wheel mode, local stroke echo, zoom controls, and optional text panel.
- PyInstaller packaging into `dist/VoiceInput.exe` using `VoiceInput.spec`.

## Technology Stack

Desktop/server:

- Python 3
- aiohttp for HTTP and WebSocket server
- asyncio for server runtime
- threading and queue for Tkinter-to-asyncio server lifecycle coordination
- tkinter / ttk for the Windows desktop UI
- ctypes + Win32 `SendInput` and `GetSystemMetrics` for input injection and screen coordinate handling
- Pillow for QR display and JPEG encoding
- qrcode for desktop QR generation
- mss for screen capture
- PyInstaller for Windows EXE packaging

Web clients:

- HTML, CSS, and browser JavaScript
- Browser WebSocket API
- Canvas 2D API for mobile remote screen display and local ink overlay
- Pointer Events, including coalesced/raw pointer events where available

Mobile app:

- Flutter / Dart
- `dart:io` WebSocket
- Material 3 UI
- `mobile_scanner` for QR scanning
- Android `INTERNET` and `CAMERA` permissions
- Android cleartext traffic enabled for LAN `ws://` and `http://`

## Engineering Design Notes

Configuration is intentionally lightweight: token and port are created or edited in the desktop UI, while `server.py` also supports command-line `--host`, `--port`, `--token`, and `--test-text` for direct server usage or quick injection testing.

The server is tightly coupled to Windows. `server.py` imports `ctypes.WinDLL("user32")` at module import time, so the main Windows implementation cannot be imported on non-Windows hosts. There is a separate `macOS_version/` directory, but it is outside the `start_desktop_client.bat` path.

Security is scoped to a trusted LAN plus a bearer token in the URL and message body. There is no HTTPS/WSS, account system, pairing protocol, origin allowlist, or rate limiting. That is appropriate for a personal local tool, but not for public exposure.

Failure handling is pragmatic but minimal. Web clients reconnect automatically; server handlers log errors and send JSON error messages. There is no persistent connection registry, structured logging, metrics, or backpressure strategy beyond basic message size limits and input length caps.

Testing is light. The only explicit test found is `mobile_app/test/widget_test.dart`, which checks that the Flutter UI renders key labels. There are no Python unit tests for `common_prefix_len`, `TextSession`, protocol validation, or coordinate mapping.

The most important design tradeoff is the text correction algorithm. It is simple and responsive, but depends on the target app focus and caret position staying stable. A future target-window lock, accessibility integration, or clipboard fallback would reduce accidental edits in more complex workflows.

## Suggested Next Reading

- `server.py`: read `TextSession`, `type_text`, `create_app`, `/ws`, `/screen`, and `/pointer` together; this is where the actual bridge behavior lives.
- `desktop_client.py`: read `DesktopClient._start_server()` and `BridgeServerThread`; this explains how the BAT entrypoint becomes a desktop-managed server.
- `static/tablet.html`: read connection setup, pointer conversion, zoom handling, wheel handling, and local echo logic; this is the most complex client.
- `mobile_app/lib/main.dart`: read URL parsing, WebSocket reconnect, queueing, and QR scan flow; this is the installable phone client.
- `VoiceInput.spec` and `PACKAGING.md`: read these when changing dependencies or rebuilding the Windows EXE.
