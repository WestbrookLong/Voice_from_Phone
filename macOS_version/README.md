# iPad Whiteboard Bridge for macOS

This is a standalone macOS version of `tablet_whiteboard`.

It does not stream the Mac screen to the iPad. The iPad page renders strokes locally on a white canvas, then sends normalized pointer events to the Mac. The Mac maps those events to the selected display and injects mouse down, move, and up events with CoreGraphics.

## Start

```bash
cd macOS_version
./start_desktop_client.sh
```

The script creates `.venv` if needed, installs `requirements.txt`, and opens the desktop control window. Click **Start service**, then open or scan the exact iPad URL shown in that window.

The URL looks like:

```text
http://<mac-lan-ip>:8791/?token=<token>
```

The desktop window appends a `v=` cache-busting parameter, so iPad Safari does not reuse an old page after code changes.

The CLI server is also available for debugging:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python server.py --port 8791
```

## macOS Permission

macOS blocks synthetic mouse input unless the running app is allowed to control the computer. If the iPad connects but strokes do not affect the Mac, open:

```text
System Settings -> Privacy & Security -> Accessibility
```

Enable Terminal, iTerm, Python, or the packaged app that starts this bridge. After changing the permission, restart the terminal or app.

## Behavior

- The page is a local white canvas.
- Pen draws black strokes locally.
- Eraser only erases the local iPad canvas.
- Clear only clears the local iPad canvas.
- Every stroke still maps to Mac mouse drag events.
- Switch drawing tools in the Mac app manually.
- Coordinates are fixed proportional mapping to display 1 by default.

## Input Design

The browser client is structured as two independent layers:

- `StrokeEngine`: owns local canvas rendering and pointer lifecycle.
- `PointerTransport`: owns WebSocket reconnects and Mac event delivery.

This keeps local drawing responsive even if the network is slow. Mouse `down` and `up` events are sent as priority messages. Mouse `move` events are batched in short 8 ms windows and can be dropped if the WebSocket buffer grows too large.

Fast repeated taps are handled explicitly. If a new pointer starts before the previous one has cleanly ended, the old stroke is force-finished before the new stroke begins. The page also listens for `pointercancel`, `lostpointercapture`, page blur, and page visibility changes so the Mac mouse button is not left stuck.

Very short strokes are normalized. On iPad browsers, a short mark can arrive as only `pointerdown` and `pointerup` with no meaningful `pointermove`. The client expands that into a minimum visible local stroke and sends a synthetic mouse move before the mouse-up event, so Mac drawing apps treat it as a drag stroke instead of a click.

The canvas itself has no click mode. Every canvas interaction is interpreted as a stroke. Toolbar buttons only change the local tool or clear the local canvas.

The server has the same safety guard: if a connection closes while the mouse button is down, it sends a final mouse-up event.

## Options

```bash
.venv/bin/python server.py --port 8791 --monitor 1 --token fixed-token
```

- `--monitor`: target display number, default `1`.
- `--port`: server port, default `8791`.
- `--token`: fixed URL token. If omitted, a random token is generated.
