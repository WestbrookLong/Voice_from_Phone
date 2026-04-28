# Whiteboard Bridge iPad App

Native Flutter iPad client for the Windows whiteboard pointer bridge in
`../tablet_whiteboard`.

The app does not embed a browser and does not stream the PC screen. It draws on a
local white canvas immediately, then sends normalized pointer events to the PC
over WebSocket.

## Behavior

- Pen draws black strokes locally.
- Eraser only erases the local iPad canvas.
- Clear only clears the local canvas.
- Every stroke maps to PC mouse down, move, and up events.
- Switch tools in the PC drawing app manually.
- Coordinates are fixed proportional mapping to the PC monitor returned by the server.
- Fast repeated strokes force-finish the previous stroke before starting the next one.
- Move events are batched in 8 ms windows; down and up events are sent immediately.
- If the app goes inactive while a stroke is active, it sends a final mouse-up event.

## PC side

Start the existing bridge:

```powershell
cd D:\Users\WESTBROOK\Projects\Voice_input\tablet_whiteboard
start_whiteboard.bat
```

The PC window prints a URL like:

```text
http://10.28.101.46:8791/?token=...
```

Paste that URL into the iPad app's Connect dialog.

## iPad install

This repository is on Windows, so it can generate and validate the Flutter iOS
project, but it cannot produce a signed `.ipa`. To install on an iPad, open this
folder on macOS with Xcode installed:

```bash
cd ipad_whiteboard_app
flutter pub get
flutter run -d <your-ipad-device-id>
```

For sharing as a downloadable app, archive/sign it from Xcode and distribute via
TestFlight, Apple Developer ad hoc distribution, or an MDM/enterprise channel.
