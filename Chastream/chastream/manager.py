from __future__ import annotations

import os
import secrets
import shutil
import threading
from dataclasses import asdict
from pathlib import Path

from .analysis import QwenConversationAnalyst
from .audio import FsmnVadProcessor, WaveRecorder
from .config import AppSettings, DATA_ROOT, PROFILES_ROOT
from .dialogue import DialogueResolver, dialogue_to_markdown
from .models import SessionState
from .storage import ProfileRepository, SessionRepository
from .transcription import DashScopeTemporaryUploader, ParaformerTimestampProvider
from .voiceprint import VoiceprintService


class ChastreamManager:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.settings = AppSettings.load()
        self.sessions = SessionRepository()
        self.profiles = ProfileRepository()
        self.voiceprints = VoiceprintService(repository=self.profiles)
        self.active: SessionState | None = None
        self.recorder: WaveRecorder | None = None
        self.worker: threading.Thread | None = None
        self.voiceprint_recorder: WaveRecorder | None = None
        self.voiceprint_draft_name = ""
        self.voiceprint_draft_paths: list[Path] = []
        self.voiceprint_error: str | None = None

    def start_recording(self, title: str, speaker_mode: str, device: int | None = None) -> dict:
        with self.lock:
            if self.voiceprint_recorder and self.voiceprint_recorder.is_alive():
                raise RuntimeError("请先停止声纹样本录制。")
            if self.recorder and self.recorder.is_alive():
                raise RuntimeError("A recording is already in progress.")
            session = self.sessions.create(title, speaker_mode)
            session.status = "recording"
            session.stage_message = "正在录音"
            recorder = WaveRecorder(Path(session.audio_path), device=device)
            self.active = session
            self.recorder = recorder
            self.sessions.save(session)
            recorder.start()
        recorder.ready.wait(timeout=8)
        if recorder.error:
            self._fail(recorder.error)
            raise RuntimeError(recorder.error)
        return self.state()

    def pause_recording(self) -> dict:
        with self.lock:
            if not self.recorder or not self.recorder.is_alive() or not self.active:
                raise RuntimeError("No active recording.")
            self.recorder.pause()
            self.active.status = "paused"
            self.active.stage_message = "已暂停"
            self.sessions.save(self.active)
        return self.state()

    def resume_recording(self) -> dict:
        with self.lock:
            if not self.recorder or not self.recorder.is_alive() or not self.active:
                raise RuntimeError("No paused recording.")
            self.recorder.resume()
            self.active.status = "recording"
            self.active.stage_message = "正在录音"
            self.sessions.save(self.active)
        return self.state()

    def stop_and_process(self) -> dict:
        with self.lock:
            if not self.recorder or not self.active:
                raise RuntimeError("No active recording.")
            recorder = self.recorder
            session = self.active
            recorder.stop()
        recorder.join(timeout=15)
        if recorder.is_alive():
            raise RuntimeError("Recorder did not stop in time.")
        if recorder.error:
            self._fail(recorder.error)
            raise RuntimeError(recorder.error)
        with self.lock:
            session.status = "queued"
            session.stage_message = "等待处理"
            self.sessions.save(session)
            self.recorder = None
            self.worker = threading.Thread(target=self._process, args=(session,), daemon=True)
            self.worker.start()
        return self.state()

    def process_existing(self, audio_path: Path, title: str, speaker_mode: str) -> dict:
        session = self.sessions.create(title, speaker_mode)
        target = Path(session.audio_path)
        target.write_bytes(audio_path.read_bytes())
        with self.lock:
            self.active = session
            self.worker = threading.Thread(target=self._process, args=(session,), daemon=True)
            self.worker.start()
        return self.state()

    def update_settings(self, payload: dict) -> dict:
        with self.lock:
            for key in self.settings.__dataclass_fields__:
                if key in payload:
                    setattr(self.settings, key, payload[key])
            self.settings.save()
        return self.state()

    def state(self) -> dict:
        with self.lock:
            active = self.active.snapshot() if self.active else None
            recorder = self.recorder
            voiceprint_recorder = self.voiceprint_recorder
            return {
                "activeSession": active,
                "recording": bool(recorder and recorder.is_alive() and not recorder.pause_event.is_set()),
                "paused": bool(recorder and recorder.is_alive() and recorder.pause_event.is_set()),
                "processing": bool(self.worker and self.worker.is_alive()),
                "recordedSeconds": round(recorder.frames_written / 16000, 1) if recorder else 0,
                "voiceprintRecording": bool(voiceprint_recorder and voiceprint_recorder.is_alive()),
                "voiceprintRecordedSeconds": (
                    round(voiceprint_recorder.frames_written / 16000, 1) if voiceprint_recorder else 0
                ),
                "voiceprintDraft": {
                    "name": self.voiceprint_draft_name,
                    "sampleCount": len(self.voiceprint_draft_paths),
                    "samplePaths": [str(path) for path in self.voiceprint_draft_paths],
                    "error": self.voiceprint_error,
                },
                "settings": asdict(self.settings),
                "profiles": [asdict(item) for item in self.profiles.load_all()],
                "recentSessions": self.sessions.list_recent(),
                "dataRoot": str(DATA_ROOT),
                "apiConfigured": bool(os.environ.get("DASHSCOPE_API_KEY", "").strip()),
                "modelAvailability": self._model_availability(),
            }

    def start_voiceprint_sample(self, name: str, device: int | None = None) -> dict:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("请先填写声纹姓名。")
        with self.lock:
            if self.recorder and self.recorder.is_alive():
                raise RuntimeError("请先停止会话录音。")
            if self.voiceprint_recorder and self.voiceprint_recorder.is_alive():
                raise RuntimeError("声纹样本正在录制。")
            if self.voiceprint_draft_name and self.voiceprint_draft_name != clean_name:
                raise RuntimeError(f"当前正在为“{self.voiceprint_draft_name}”采集样本，请先完成或清空。")
            draft_dir = PROFILES_ROOT / "drafts"
            draft_dir.mkdir(parents=True, exist_ok=True)
            path = draft_dir / f"{secrets.token_hex(8)}.wav"
            recorder = WaveRecorder(path, device=device)
            self.voiceprint_draft_name = clean_name
            self.voiceprint_error = None
            self.voiceprint_recorder = recorder
            recorder.start()
        recorder.ready.wait(timeout=8)
        if recorder.error:
            with self.lock:
                self.voiceprint_recorder = None
                self.voiceprint_error = recorder.error
            raise RuntimeError(recorder.error)
        return self.state()

    def stop_voiceprint_sample(self) -> dict:
        with self.lock:
            recorder = self.voiceprint_recorder
            if not recorder or not recorder.is_alive():
                raise RuntimeError("当前没有正在录制的声纹样本。")
            recorder.stop()
        recorder.join(timeout=15)
        if recorder.is_alive():
            raise RuntimeError("声纹录音未能及时停止。")
        if recorder.error:
            with self.lock:
                self.voiceprint_error = recorder.error
                self.voiceprint_recorder = None
            raise RuntimeError(recorder.error)
        duration_seconds = recorder.frames_written / 16000
        with self.lock:
            self.voiceprint_recorder = None
            if duration_seconds < 3:
                recorder.output_path.unlink(missing_ok=True)
                self.voiceprint_error = "样本不足 3 秒，请重新录制。"
                raise ValueError(self.voiceprint_error)
            self.voiceprint_draft_paths.append(recorder.output_path)
            self.voiceprint_error = None
        return self.state()

    def finish_voiceprint_enrollment(self) -> dict:
        with self.lock:
            if self.voiceprint_recorder and self.voiceprint_recorder.is_alive():
                raise RuntimeError("请先停止当前声纹样本。")
            name = self.voiceprint_draft_name
            paths = list(self.voiceprint_draft_paths)
        if not name or not paths:
            raise RuntimeError("还没有可注册的声纹样本。")
        if len(paths) < 3:
            raise RuntimeError("请至少录制 3 段样本后再完成注册。")
        profile = self.enroll_profile(name, paths)
        self.clear_voiceprint_draft()
        return profile

    def clear_voiceprint_draft(self) -> dict:
        with self.lock:
            if self.voiceprint_recorder and self.voiceprint_recorder.is_alive():
                raise RuntimeError("请先停止当前声纹样本。")
            paths = list(self.voiceprint_draft_paths)
            self.voiceprint_draft_paths = []
            self.voiceprint_draft_name = ""
            self.voiceprint_error = None
        for path in paths:
            path.unlink(missing_ok=True)
        return self.state()

    def enroll_profile(self, name: str, sample_paths: list[Path]) -> dict:
        if not sample_paths:
            raise ValueError("请选择至少一个 WAV 声纹样本。")
        profile_dir = PROFILES_ROOT / "samples"
        profile_dir.mkdir(parents=True, exist_ok=True)
        local_samples = []
        vad = FsmnVadProcessor()
        for index, source in enumerate(sample_paths, start=1):
            if source.suffix.lower() != ".wav":
                raise ValueError("声纹注册目前只支持 WAV 文件。")
            target = profile_dir / f"{secrets.token_hex(4)}-{index}-{source.name}"
            shutil.copy2(source, target)
            clean_target = target.with_name(f"{target.stem}.speech.wav")
            try:
                cleaned, _ = vad.clean(target, clean_target)
            except Exception:
                cleaned = target
            local_samples.append(cleaned)
        profile = self.voiceprints.enroll(name, local_samples)
        return asdict(profile)

    def delete_profile(self, profile_id: str) -> dict:
        self.profiles.delete(profile_id)
        return self.state()

    def load_session(self, session_id: str) -> dict:
        with self.lock:
            if self.recorder and self.recorder.is_alive():
                raise RuntimeError("录音期间不能切换历史会话。")
            if self.worker and self.worker.is_alive():
                raise RuntimeError("当前会话仍在处理中，请完成后再查看历史会话。")
            self.active = self.sessions.load(session_id)
        return self.state()

    def copy_markdown(self, kind: str) -> str:
        with self.lock:
            if not self.active:
                raise RuntimeError("没有可复制的会话。")
            name = "analysis.md" if kind == "analysis" else "dialogue.md"
            path = self.sessions.directory(self.active.id) / name
        if not path.exists():
            raise RuntimeError("对应内容尚未生成。")
        return path.read_text(encoding="utf-8")

    def _process(self, session: SessionState) -> None:
        try:
            profiles = self.profiles.load_all()
            if not profiles:
                raise RuntimeError("请先注册至少一个声纹档案，再处理对话。")

            self._stage(session, "uploading", "正在上传录音")
            uploader = DashScopeTemporaryUploader(model=self.settings.asr_model)
            session.uploaded_url = uploader.upload(Path(session.audio_path))
            self.sessions.save(session)

            self._stage(session, "transcribing", "正在进行整场转写并提取词级时间戳")
            provider = ParaformerTimestampProvider(
                model=self.settings.asr_model,
                vocabulary_id=self.settings.asr_vocabulary_id,
                language_hints=[
                    item.strip()
                    for item in self.settings.asr_language_hints.split(",")
                    if item.strip()
                ],
            )
            session.task_id = provider.submit(session.uploaded_url)
            self.sessions.save(session)
            task = provider.wait(session.task_id)
            session.transcription_url = str(task.get("transcription_url", ""))
            raw_transcription, sentences, words = provider.fetch_transcription(session.transcription_url)
            if not words:
                raise RuntimeError("Paraformer did not return timestamped transcript words.")
            session.transcript_sentences = [asdict(item) for item in sentences]
            session.timed_words = [asdict(item) for item in words]
            self.sessions.write_json(session.id, "transcription.raw.json", raw_transcription)
            self.sessions.write_json(session.id, "transcript.sentences.json", session.transcript_sentences)
            self.sessions.write_json(session.id, "transcript.words.json", session.timed_words)
            self.sessions.save(session)

            self._stage(session, "matching", "正在按句切片、匹配声纹并进行句内精切")
            resolver = DialogueResolver(
                self.voiceprints,
                threshold=float(self.settings.voiceprint_threshold),
                margin=float(self.settings.voiceprint_margin),
                minimum_speech_ms=int(self.settings.minimum_speech_ms),
                scl_trigger_threshold=float(self.settings.scl_trigger_threshold),
            )
            change_points, segments, resolved, diagnostics = resolver.resolve(
                Path(session.audio_path),
                words,
                profiles,
                self.sessions.directory(session.id) / "segments",
                enable_scl=bool(self.settings.enable_scl and session.speaker_mode == "two"),
            )
            session.change_points = change_points
            session.segments = [asdict(item) for item in segments]
            session.resolved_utterances = [asdict(item) for item in resolved]
            self.sessions.write_json(session.id, "change-points.json", session.change_points)
            self.sessions.write_json(session.id, "sentence-speaker-units.json", session.segments)
            self.sessions.write_json(session.id, "voiceprint.diagnostics.json", diagnostics)
            self.sessions.write_json(session.id, "dialogue.json", session.resolved_utterances)
            self.sessions.write_text(session.id, "dialogue.md", dialogue_to_markdown(resolved))
            self.sessions.save(session)

            self._stage(session, "analyzing", "正在整理完整对话")
            analyst = QwenConversationAnalyst(self.settings.qwen_model)
            session.analysis = analyst.analyze(resolved)
            self.sessions.write_json(session.id, "analysis.json", session.analysis)
            self.sessions.write_text(session.id, "analysis.md", analyst.to_markdown(session.analysis))
            session.status = "done"
            session.stage_message = "已完成"
            self.sessions.save(session)
        except Exception as exc:
            self._fail(str(exc), session=session)

    def _stage(self, session: SessionState, status: str, message: str) -> None:
        with self.lock:
            session.status = status
            session.stage_message = message
            session.error = None
            self.sessions.save(session)

    def _fail(self, message: str, session: SessionState | None = None) -> None:
        with self.lock:
            target = session or self.active
            if target:
                target.status = "failed"
                target.stage_message = "处理失败"
                target.error = message
                self.sessions.save(target)

    def _model_availability(self) -> dict:
        available, message = self.voiceprints.provider.available()
        return {"campPlus": available, "message": message}
