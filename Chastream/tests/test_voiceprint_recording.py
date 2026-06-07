from pathlib import Path

import pytest

import chastream.manager as manager_module
from chastream.manager import ChastreamManager


class FakeReady:
    def wait(self, timeout=None):
        return True


class FakeRecorder:
    frames = 16000 * 5

    def __init__(self, output_path: Path, device=None):
        self.output_path = output_path
        self.device = device
        self.frames_written = self.frames
        self.error = None
        self.ready = FakeReady()
        self.alive = False

    def start(self):
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_bytes(b"sample")
        self.alive = True

    def is_alive(self):
        return self.alive

    def stop(self):
        self.alive = False

    def join(self, timeout=None):
        return None


def test_records_voiceprint_sample_to_draft(monkeypatch, tmp_path):
    monkeypatch.setattr(manager_module, "PROFILES_ROOT", tmp_path)
    monkeypatch.setattr(manager_module, "WaveRecorder", FakeRecorder)
    manager = ChastreamManager()

    manager.start_voiceprint_sample("测试者", device=3)
    state = manager.stop_voiceprint_sample()

    assert state["voiceprintDraft"]["name"] == "测试者"
    assert state["voiceprintDraft"]["sampleCount"] == 1
    assert Path(state["voiceprintDraft"]["samplePaths"][0]).exists()


def test_rejects_too_short_voiceprint_sample(monkeypatch, tmp_path):
    class ShortRecorder(FakeRecorder):
        frames = 16000 * 2

    monkeypatch.setattr(manager_module, "PROFILES_ROOT", tmp_path)
    monkeypatch.setattr(manager_module, "WaveRecorder", ShortRecorder)
    manager = ChastreamManager()

    manager.start_voiceprint_sample("测试者")
    with pytest.raises(ValueError, match="不足 3 秒"):
        manager.stop_voiceprint_sample()

    assert manager.state()["voiceprintDraft"]["sampleCount"] == 0


def test_requires_three_samples_before_finishing(monkeypatch, tmp_path):
    monkeypatch.setattr(manager_module, "PROFILES_ROOT", tmp_path)
    monkeypatch.setattr(manager_module, "WaveRecorder", FakeRecorder)
    manager = ChastreamManager()
    manager.start_voiceprint_sample("测试者")
    manager.stop_voiceprint_sample()

    with pytest.raises(RuntimeError, match="至少录制 3 段"):
        manager.finish_voiceprint_enrollment()

