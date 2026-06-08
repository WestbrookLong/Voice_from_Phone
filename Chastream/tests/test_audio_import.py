import wave

import numpy as np
import soundfile as sf

from chastream.audio import normalize_uploaded_wav


def _write_tone(path, sample_rate, channels, subtype):
    duration_seconds = 1.25
    timeline = np.arange(int(sample_rate * duration_seconds), dtype=np.float32) / sample_rate
    tone = 0.25 * np.sin(2 * np.pi * 440 * timeline)
    samples = np.column_stack([tone] * channels)
    sf.write(path, samples, sample_rate, subtype=subtype, format="WAV")
    return duration_seconds


def test_normalizes_uploaded_wav_to_processing_format(tmp_path):
    source = tmp_path / "source-24bit-stereo.wav"
    target = tmp_path / "audio.wav"
    expected_duration = _write_tone(source, 48000, 2, "PCM_24")

    converted = normalize_uploaded_wav(source, target)

    assert converted is True
    with wave.open(str(target), "rb") as reader:
        assert reader.getframerate() == 16000
        assert reader.getnchannels() == 1
        assert reader.getsampwidth() == 2
        assert abs(reader.getnframes() / reader.getframerate() - expected_duration) < 0.01


def test_compatible_uploaded_wav_is_copied_without_conversion(tmp_path):
    source = tmp_path / "source-compatible.wav"
    target = tmp_path / "audio.wav"
    _write_tone(source, 16000, 1, "PCM_16")

    converted = normalize_uploaded_wav(source, target)

    assert converted is False
    assert target.read_bytes() == source.read_bytes()
