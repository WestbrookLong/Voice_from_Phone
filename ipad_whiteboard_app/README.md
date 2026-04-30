# Whiteboard Bridge iPad App

This is the native iPad client for both `../tablet_whiteboard` and
`../macOS_version/macOS_whiteboard`. It does not embed the Safari whiteboard
page. The app talks directly to the desktop bridge through the same endpoints:

- `GET /snapshot`
- `WS /screen`
- `WS /pointer`

## Current feature set

- Pen, straight line, eraser, and local undo.
- Pen color picker and pen thickness popover on the pen button.
- Local eraser clears only the iPad stroke layer; PC shot and screen stream stay
  as the bottom background.
- Floating square Pen, Line, Eraser, and Undo buttons. Each button can be dragged
  independently.
- Settings panel changes the selected floating button's size and opacity only.
- Pen, Line, Eraser, and Undo taps pass through as PC clicks at the same mapped
  position. PC Shot, Stream, Area, Settings, Color, and Clear do not pass through.
- PC Shot snapshot background.
- Optional screen stream background.
- Hide/show PC background.
- Editable drawing area. Inside the area the app draws locally and sends pointer
  input. Outside the area it only sends pointer input to the PC.
- Two-finger pinch zoom. Snapshot/screen stream and local strokes zoom together;
  PC coordinates are inverse-mapped to the zoomed view.
- High-rate Flutter pointer handling with 8 ms WebSocket move batches, matching
  the current PC bridge protocol.

## Desktop side

Windows:

```powershell
cd D:\Users\WESTBROOK\Projects\Voice_input\tablet_whiteboard
start_whiteboard.bat
```

macOS:

```bash
cd /Users/ayana/Voice_from_Phone/macOS_version/macOS_whiteboard
./start_desktop_client.sh
```

The desktop bridge window shows a URL like:

```text
http://10.28.101.46:8791/?token=...
```

Open the iPad app and paste that URL into the Connect dialog.

## iPad install

This repository is on Windows, so it can validate Flutter/Dart code but cannot
produce a signed iPad build. To install on an iPad, open this folder on macOS
with Flutter and Xcode installed:

```bash
cd ipad_whiteboard_app
flutter pub get
flutter run -d <your-ipad-device-id>
```

For a downloadable build, archive/sign the iOS Runner target from Xcode and
distribute it through TestFlight, ad hoc distribution, enterprise/MDM, or a
developer-device install.

The iOS `Info.plist` already allows local network HTTP/WebSocket access for the
PC bridge.
