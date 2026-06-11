from __future__ import annotations

import queue
import shutil
import threading
import wave
from math import gcd
from pathlib import Path

import numpy as np


SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2
IMPORT_BLOCK_SECONDS = 30
IMPORT_OVERLAP_SECONDS = 0.25


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


def normalize_uploaded_wav(source: Path, target: Path) -> bool:
    """Copy a compatible WAV or normalize an uploaded WAV for local processing."""
    import soundfile as sf
    from scipy.signal import resample_poly

    source = Path(source)
    target = Path(target)
    if not source.is_file():
        raise FileNotFoundError(f"导入的音频文件不存在：{source}")

    try:
        with sf.SoundFile(str(source), "r") as reader:
            is_wav = reader.format == "WAV"
            is_compatible = (
                is_wav
                and reader.samplerate == SAMPLE_RATE
                and reader.channels == CHANNELS
                and reader.subtype == "PCM_16"
            )
            input_rate = int(reader.samplerate)
            input_channels = int(reader.channels)
            total_frames = int(reader.frames)
    except Exception as exc:
        raise RuntimeError(f"无法读取导入的 WAV 文件：{exc}") from exc

    if not is_wav:
        raise RuntimeError("导入文件不是有效的 WAV 音频。")
    if input_rate <= 0 or input_channels <= 0 or total_frames <= 0:
        raise RuntimeError("导入的 WAV 文件没有可处理的音频数据。")

    target.parent.mkdir(parents=True, exist_ok=True)
    if is_compatible:
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)
        return False

    temporary = target.with_name(f"{target.stem}.normalizing{target.suffix}")
    temporary.unlink(missing_ok=True)
    common = gcd(SAMPLE_RATE, input_rate)
    up = SAMPLE_RATE // common
    down = input_rate // common
    block_frames = max(1, input_rate * IMPORT_BLOCK_SECONDS)
    overlap_frames = max(1, int(input_rate * IMPORT_OVERLAP_SECONDS))

    try:
        with sf.SoundFile(str(source), "r") as reader, sf.SoundFile(
            str(temporary),
            "w",
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            subtype="PCM_16",
            format="WAV",
        ) as writer:
            for start in range(0, total_frames, block_frames):
                end = min(total_frames, start + block_frames)
                read_start = max(0, start - overlap_frames)
                read_end = min(total_frames, end + overlap_frames)
                reader.seek(read_start)
                samples = reader.read(
                    read_end - read_start,
                    dtype="float32",
                    always_2d=True,
                )
                mono = samples.mean(axis=1, dtype=np.float32)
                converted = resample_poly(mono, up, down).astype(np.float32, copy=False)

                global_output_start = round(start * SAMPLE_RATE / input_rate)
                global_output_end = round(end * SAMPLE_RATE / input_rate)
                local_output_origin = round(read_start * SAMPLE_RATE / input_rate)
                local_start = global_output_start - local_output_origin
                local_end = global_output_end - local_output_origin
                writer.write(converted[local_start:local_end])
        temporary.replace(target)
    except Exception as exc:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"转换导入音频失败：{exc}") from exc
    return True


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
        with self._lock:
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
