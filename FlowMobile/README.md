# FlowMobile

Android MVP for the next phase of `Flow Voice`: move the voice command loop into a system input method so WeChat and other apps can be controlled without relying on a desktop relay.

## Scope

- Custom Android IME (`FlowMobileImeService`)
- Offline continuous speech recognition using Vosk and the bundled `model-cn` asset
- In-IME text preview via composing text
- Trailing English commands handled inside the IME:
  - `enter`
  - `back`
  - `backspace` / `back space`
  - `delete all`
- Optional accessibility fallback to click `发送` / `Send` when the app does not expose an IME send action

## Key files

- `app/src/main/java/com/westbrook/flowmobile/MainActivity.kt`
- `app/src/main/java/com/westbrook/flowmobile/ime/FlowMobileImeService.kt`
- `app/src/main/java/com/westbrook/flowmobile/ime/VoiceCommandProcessor.kt`
- `app/src/main/java/com/westbrook/flowmobile/ime/FlowAccessibilityService.kt`

## Notes

- This is a native Android project, not Flutter.
- The current build target is an MVP skeleton: stable enough to validate the architecture, not yet tuned for long-session production use.
- The bundled offline model is `vosk-model-small-cn-0.22`.
