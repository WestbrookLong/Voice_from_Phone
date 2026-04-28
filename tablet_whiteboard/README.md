# Mobile Remote Bridge

This is a standalone low-latency whiteboard mode.

It does not stream the PC screen to the mobile device. The mobile page renders strokes locally on a white canvas, then sends normalized pointer events to the PC. The PC maps those events to the selected monitor and injects mouse down, move, and up events.

## Start

```powershell
cd D:\Users\WESTBROOK\Projects\Voice_input\tablet_whiteboard
python server.py
```

Or double-click:

```text
start_whiteboard.bat
```

This opens a desktop control window, matching the connection flow of the main
voice-input client. Click **Start service**, then open or scan the exact mobile remote URL
shown in that window.

The URL looks like:

```text
Open on mobile device: http://<pc-lan-ip>:8791/?token=<token>
```

The desktop window appends a `v=` cache-busting parameter, so the mobile browser does not
reuse an old page after code changes.

The CLI server is still available for debugging:

```powershell
python server.py --port 8791
```

## Behavior

- The page is a local whiteboard canvas.
- Pen supports custom colors and stroke width.
- Line mode draws straight-line strokes.
- Highlighter mode draws translucent wide strokes.
- Eraser only erases the local mobile canvas.
- Undo and redo work on local strokes.
- Clear only clears the local mobile canvas.
- Paper backgrounds include blank, lined, grid, and dot paper.
- `PC Shot` captures the current PC screen once and displays it as the canvas
  background for visual alignment. It does not stream or auto-refresh.
- `Hide PC` toggles the captured PC snapshot without deleting local strokes.
- Every stroke still maps to PC mouse drag events.
- Switch drawing tools in the PC app manually.
- Coordinates are fixed proportional mapping to monitor 1 by default.

Local drawing options such as color, width, highlighter, and paper style only affect
the mobile canvas. The PC side receives mouse movement only, so the target PC drawing
app's color and brush settings still need to be selected there.

## Input design

The browser client is structured as two independent layers:

- `StrokeEngine`: owns local canvas rendering and pointer lifecycle.
- `PointerTransport`: owns WebSocket reconnects and PC event delivery.

This keeps local drawing responsive even if the network is slow. Mouse `down` and `up`
events are sent as priority messages. Mouse `move` events are batched in short 8 ms
windows and can be dropped if the WebSocket buffer grows too large.

Fast repeated taps are handled explicitly. If a new pointer starts before the previous
one has cleanly ended, the old stroke is force-finished before the new stroke begins.
The page also listens for `pointercancel`, `lostpointercapture`, page blur, and page
visibility changes so the PC mouse button is not left stuck.

Very short strokes are normalized. On mobile browsers, a short mark can arrive as only
`pointerdown` and `pointerup` with no meaningful `pointermove`. The client expands
that into a minimum visible local stroke and sends a synthetic mouse move before the
mouse-up event, so PC drawing apps treat it as a drag stroke instead of a click.

The canvas itself has no click mode. Every canvas interaction is interpreted as a
stroke. Toolbar buttons only change the local tool or clear the local canvas.

The server has the same safety guard: if a connection closes while the mouse button is
down, it sends a final mouse-up event.

## Options

```powershell
python server.py --port 8791 --monitor 1 --token fixed-token
```

- `--monitor`: target display number, default `1`.
- `--port`: server port, default `8791`.
- `--token`: fixed URL token. If omitted, a random token is generated.
