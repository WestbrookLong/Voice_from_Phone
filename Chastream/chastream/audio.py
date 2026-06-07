from __future__ import annotations

import queue
import threading
import wave
from pathlib import Path

import numpy as np


SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2


class WaveRecorder(threading.Thread):
    def __init__(self, output_path: Path, device: int | None = None) -> None:
        super().__init__(daemon=True)
        self.output_path = output_path
        self.device = device
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.ready = threading.Event()
        self.error: str | None = None
        self.frames_written = 0
        self.audio_queue: queue.Queue[bytes] = queue.Queue(maxsize=128)

    def run(self) -> None:
        try:
            import sounddevice as sd

            self.output_path.parent.mkdir(parents=True, exist_ok=True)

            def callback(indata, frames, time_info, status) -> None:
                if self.pause_event.is_set():
                    return
                try:
                    self.audio_queue.put_nowait(bytes(indata))
                except queue.Full:
                    pass

            with wave.open(str(self.output_path), "wb") as writer:
                writer.setnchannels(CHANNELS)
                writer.setsampwidth(SAMPLE_WIDTH)
                writer.setframerate(SAMPLE_RATE)
                with sd.RawInputStream(
                    samplerate=SAMPLE_RATE,
                    blocksize=1600,
                    dtype="int16",
                    channels=CHANNELS,
                    device=self.device,
                    callback=callback,
                ):
                    self.ready.set()
                    while not self.stop_event.is_set() or not self.audio_queue.empty():
                        try:
                            chunk = self.audio_queue.get(timeout=0.1)
                        except queue.Empty:
                            continue
                        writer.writeframesraw(chunk)
                        self.frames_written += len(chunk) // SAMPLE_WIDTH
        except Exception as exc:
            self.error = str(exc)
            self.ready.set()

    def stop(self) -> None:
        self.stop_event.set()

    def pause(self) -> None:
        self.pause_event.set()

    def resume(self) -> None:
        self.pause_event.clear()


def list_input_devices() -> list[dict]:
    import sounddevice as sd

    devices = []
    for index, device in enumerate(sd.query_devices()):
        if int(device.get("max_input_channels", 0)) > 0:
            devices.append(
                {
                    "id": index,
                    "name": str(device.get("name", f"Input {index}")),
                    "channels": int(device.get("max_input_channels", 0)),
                }
            )
    return devices


def read_wav_mono(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as reader:
        sample_rate = reader.getframerate()
        channels = reader.getnchannels()
        width = reader.getsampwidth()
        frames = reader.readframes(reader.getnframes())
    if width != 2:
        raise RuntimeError("Only 16-bit PCM WAV is supported.")
    samples = np.frombuffer(frames, dtype="<i2")
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1).astype(np.int16)
    return samples, sample_rate


def write_wav_mono(path: Path, samples: np.ndarray, sample_rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(np.asarray(samples, dtype="<i2").tobytes())


def slice_wav(source: Path, target: Path, start_ms: int, end_ms: int, padding_ms: int = 100) -> Path:
    samples, sample_rate = read_wav_mono(source)
    start = max(0, int((start_ms - padding_ms) * sample_rate / 1000))
    end = min(len(samples), int((end_ms + padding_ms) * sample_rate / 1000))
    write_wav_mono(target, samples[start:end], sample_rate)
    return target


def speech_quality(path: Path) -> dict:
    samples, sample_rate = read_wav_mono(path)
    if samples.size == 0:
        return {"durationMs": 0, "rms": 0.0, "usable": False}
    rms = float(np.sqrt(np.mean(samples.astype(np.float32) ** 2)))
    duration_ms = int(samples.size * 1000 / sample_rate)
    return {"durationMs": duration_ms, "rms": rms, "usable": duration_ms >= 800 and rms >= 80}


class FsmnVadProcessor:
    def __init__(self) -> None:
        self._model = None
        self._lock = threading.RLock()

    def _get_model(self):
        with self._lock:
            if self._model is None:
                from funasr import AutoModel

                self._model = AutoModel(model="fsmn-vad", device="cpu", disable_update=True)
            return self._model

    def clean(self, source: Path, target: Path, padding_ms: int = 80) -> tuple[Path, list[list[int]]]:
        result = self._get_model().generate(input=str(source), disable_pbar=True)
        ranges = (result[0].get("value") if result else None) or []
        if not ranges:
            return source, []
        samples, sample_rate = read_wav_mono(source)
        pieces = []
        normalized_ranges = []
        duration_ms = int(len(samples) * 1000 / sample_rate)
        for value in ranges:
            if not isinstance(value, (list, tuple)) or len(value) < 2:
                continue
            start_ms = max(0, int(value[0]) - padding_ms)
            end_ms = min(duration_ms, int(value[1]) + padding_ms)
            if end_ms <= start_ms:
                continue
            start = int(start_ms * sample_rate / 1000)
            end = int(end_ms * sample_rate / 1000)
            pieces.append(samples[start:end])
            normalized_ranges.append([start_ms, end_ms])
        if not pieces:
            return source, []
        write_wav_mono(target, np.concatenate(pieces), sample_rate)
        return target, normalized_ranges
