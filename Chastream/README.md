# Chastream

Desktop conversation transcription, speaker identification, and structured analysis.

## Pipeline

1. Record one 16 kHz mono PCM WAV.
2. Upload it to DashScope temporary OSS storage.
3. Run Paraformer whole-file transcription with sentence and word timestamps; cloud diarization is disabled.
4. Split the timestamped words into punctuation units, including comma-separated clauses.
5. Match every sentence unit against locally registered CAM++ voiceprints.
6. Use local SCL only to refine a possible speaker change inside one sentence unit.
7. Produce an identified dialogue and a Qwen conversation analysis.

Every output row remains a separate timestamped sentence, even when adjacent rows belong to the same person. Low-confidence audio remains `未识别发言人`.

## Configuration

Set `DASHSCOPE_API_KEY` in the environment. The optional Paraformer vocabulary ID can be configured in the desktop UI; no Tingwu App ID is required.

All generated files and model caches live under:

```text
D:\Users\WESTBROOK\Projects\Voice_input\Chastream\data
```

The application overrides ModelScope, Hugging Face, Torch, and process temporary directories so its persisted data does not use the C drive.

## Run

```powershell
pip install -r requirements.txt
.\start_chastream_debug.bat
```

The first CAM++ or SCL operation downloads the corresponding model into `data/cache`.

## Register a voiceprint

Enter a name in the voiceprint panel, then use `录制样本` to record 3 to 5 separate samples. Speak naturally for 5 to 15 seconds per sample. Stop each sample before starting the next one, then select `完成注册`.

Built-in sample recording always produces 16 kHz, mono, PCM16 WAV files using the selected microphone. Samples shorter than 3 seconds are rejected.
