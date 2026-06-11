# Chastream Mobile

Native Android client containing two workflows:

- Quick ideas: Widget or App opens `QuickRecordActivity`, records a 16 kHz
  mono PCM16 WAV, stores it locally, then uploads with WorkManager.
- Full conversations: records through the same reliable audio layer and sends
  the conversation metadata to the independent backend pipeline. The setup
  screen selects speaker collections, organization style, speaker mode,
  CAM++ thresholds and SCL behavior. Existing audio can also be imported.
- Voiceprints: create speaker collections, record a PCM16 sample as a new
  matching element, and hide or delete elements.

The Widget reads Room only. Network completion updates Room first and then
refreshes every Widget instance, so a temporary network failure never removes
the local recording.

The development default server is:

```text
http://106.53.94.254/chastream/
```

Before production, configure HTTPS and set the API token in app settings.

Build the debug APK with:

```powershell
.\gradlew.bat assembleDebug
```

Output:

```text
app/build/outputs/apk/debug/app-debug.apk
```
