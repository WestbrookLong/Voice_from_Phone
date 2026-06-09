from __future__ import annotations

import os
import secrets
import shutil
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from .analysis import QwenConversationAnalyst
from .analysis_prompts import normalize_analysis_style
from .audio import FsmnVadProcessor, WaveRecorder, normalize_uploaded_wav
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
        self.vad = FsmnVadProcessor()
        self.active: SessionState | None = None
        self.recorder: WaveRecorder | None = None
        self.worker: threading.Thread | None = None
        self.voiceprint_recorder: WaveRecorder | None = None
        self.voiceprint_draft_name = ""
        self.voiceprint_draft_paths: list[Path] = []
        self.voiceprint_error: str | None = None
        self.voiceprint_enrollment_worker: threading.Thread | None = None
        self.voiceprint_enrollment_stage = ""
        self.voiceprint_enrollment_current = 0
        self.voiceprint_enrollment_total = 0
        self.voiceprint_enrollment_error: str | None = None
        self.voiceprint_enrollment_completed_name = ""

    def start_recording(
        self,
        title: str,
        speaker_mode: str,
        selected_speaker_ids: list[str],
        device: int | None = None,
        analysis_style: str = "chat",
    ) -> dict:
        selected_speaker_ids = self._validate_selected_speakers(selected_speaker_ids)
        analysis_style = normalize_analysis_style(analysis_style)
        with self.lock:
            if self.voiceprint_recorder and self.voiceprint_recorder.is_alive():
                raise RuntimeError("请先停止声纹样本录制。")
            if self._voiceprint_enrollment_running():
                raise RuntimeError("声纹注册仍在处理中。")
            if self.recorder and self.recorder.is_alive():
                raise RuntimeError("A recording is already in progress.")
            session = self.sessions.create(
                title,
                speaker_mode,
                selected_speaker_ids,
                analysis_style,
            )
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

    def process_existing(
        self,
        audio_path: Path,
        title: str,
        speaker_mode: str,
        selected_speaker_ids: list[str],
        analysis_style: str = "chat",
    ) -> dict:
        if self._voiceprint_enrollment_running():
            raise RuntimeError("声纹注册仍在处理中。")
        selected_speaker_ids = self._validate_selected_speakers(selected_speaker_ids)
        analysis_style = normalize_analysis_style(analysis_style)
        audio_path = Path(audio_path)
        if not audio_path.is_file():
            raise FileNotFoundError(f"导入的音频文件不存在：{audio_path}")
        session = self.sessions.create(
            title,
            speaker_mode,
            selected_speaker_ids,
            analysis_style,
        )
        with self.lock:
            self.active = session
            session.status = "normalizing"
            session.stage_message = "正在检查并规范化导入音频"
            self.sessions.save(session)
            self.worker = threading.Thread(
                target=self._prepare_existing_and_process,
                args=(session, audio_path),
                daemon=True,
            )
            self.worker.start()
        return self.state()

    def _prepare_existing_and_process(self, session: SessionState, source: Path) -> None:
        try:
            normalize_uploaded_wav(source, Path(session.audio_path))
        except Exception as exc:
            self._fail(str(exc), session=session)
            return
        self._process(session)

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
                "voiceprintEnrollment": {
                    "running": self._voiceprint_enrollment_running(),
                    "stage": self.voiceprint_enrollment_stage,
                    "current": self.voiceprint_enrollment_current,
                    "total": self.voiceprint_enrollment_total,
                    "error": self.voiceprint_enrollment_error,
                    "completedName": self.voiceprint_enrollment_completed_name,
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
            if self._voiceprint_enrollment_running():
                raise RuntimeError("声纹注册仍在处理中。")
            if self.voiceprint_draft_name and self.voiceprint_draft_name != clean_name:
                raise RuntimeError(f"当前正在为“{self.voiceprint_draft_name}”采集样本，请先完成或清空。")
            draft_dir = PROFILES_ROOT / "drafts"
            draft_dir.mkdir(parents=True, exist_ok=True)
            path = draft_dir / f"{secrets.token_hex(8)}.wav"
            recorder = WaveRecorder(path, device=device)
            self.voiceprint_draft_name = clean_name
            self.voiceprint_error = None
            self.voiceprint_enrollment_error = None
            self.voiceprint_enrollment_completed_name = ""
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
            if self._voiceprint_enrollment_running():
                raise RuntimeError("声纹注册已经在处理中。")
            if self.worker and self.worker.is_alive():
                raise RuntimeError("当前对话仍在处理中，请稍后注册声纹。")
            name = self.voiceprint_draft_name
            paths = list(self.voiceprint_draft_paths)
            if not name or not paths:
                raise RuntimeError("还没有可注册的声纹样本。")
            if len(paths) < 3:
                raise RuntimeError("请至少录制 3 段样本后再完成注册。")
            self.voiceprint_enrollment_stage = "准备声纹注册"
            self.voiceprint_enrollment_current = 0
            self.voiceprint_enrollment_total = len(paths)
            self.voiceprint_enrollment_error = None
            self.voiceprint_enrollment_completed_name = ""
            self.voiceprint_enrollment_worker = threading.Thread(
                target=self._finish_voiceprint_enrollment_worker,
                args=(name, paths),
                daemon=True,
            )
            self.voiceprint_enrollment_worker.start()
        return self.state()

    def clear_voiceprint_draft(self) -> dict:
        with self.lock:
            if self.voiceprint_recorder and self.voiceprint_recorder.is_alive():
                raise RuntimeError("请先停止当前声纹样本。")
            if self._voiceprint_enrollment_running():
                raise RuntimeError("声纹注册仍在处理中，暂时不能清空样本。")
            paths = list(self.voiceprint_draft_paths)
            self.voiceprint_draft_paths = []
            self.voiceprint_draft_name = ""
            self.voiceprint_error = None
            self.voiceprint_enrollment_error = None
            self.voiceprint_enrollment_completed_name = ""
            self.voiceprint_enrollment_stage = ""
        for path in paths:
            path.unlink(missing_ok=True)
        return self.state()

    def enroll_profile(
        self,
        name: str,
        sample_paths: list[Path],
        progress: Callable[[str, int, int], None] | None = None,
    ) -> dict:
        if not sample_paths:
            raise ValueError("请选择至少一个 WAV 声纹样本。")
        profile_dir = PROFILES_ROOT / "samples"
        profile_dir.mkdir(parents=True, exist_ok=True)
        local_samples = []
        for index, source in enumerate(sample_paths, start=1):
            if source.suffix.lower() != ".wav":
                raise ValueError("声纹注册目前只支持 WAV 文件。")
            target = profile_dir / f"{secrets.token_hex(4)}-{index}-{source.name}"
            shutil.copy2(source, target)
            clean_target = target.with_name(f"{target.stem}.speech.wav")
            try:
                cleaned, _ = self.vad.clean(target, clean_target)
            except Exception:
                cleaned = target
            local_samples.append(cleaned)
            if progress:
                progress("正在清理样本", index, len(sample_paths))
        profile = self.voiceprints.enroll(
            name,
            local_samples,
            progress=(
                (lambda current, total: progress("正在提取声纹", current, total))
                if progress
                else None
            ),
        )
        return asdict(profile)

    def _finish_voiceprint_enrollment_worker(self, name: str, paths: list[Path]) -> None:
        try:
            self.enroll_profile(name, paths, progress=self._voiceprint_enrollment_progress)
            with self.lock:
                self.voiceprint_draft_paths = []
                self.voiceprint_draft_name = ""
                self.voiceprint_error = None
                self.voiceprint_enrollment_stage = "注册完成"
                self.voiceprint_enrollment_completed_name = name
            for path in paths:
                path.unlink(missing_ok=True)
        except Exception as exc:
            with self.lock:
                self.voiceprint_enrollment_stage = "注册失败"
                self.voiceprint_enrollment_error = str(exc)

    def _voiceprint_enrollment_progress(self, stage: str, current: int, total: int) -> None:
        with self.lock:
            self.voiceprint_enrollment_stage = stage
            self.voiceprint_enrollment_current = current
            self.voiceprint_enrollment_total = total

    def _voiceprint_enrollment_running(self) -> bool:
        return bool(
            self.voiceprint_enrollment_worker
            and self.voiceprint_enrollment_worker.is_alive()
        )

    def delete_profile(self, profile_id: str) -> dict:
        with self.lock:
            if self.recorder and self.recorder.is_alive():
                raise RuntimeError("录音期间不能删除参与者声纹。")
            if self.worker and self.worker.is_alive():
                raise RuntimeError("当前会话仍在处理中，不能删除参与者声纹。")
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
            profiles = self._profiles_for_session(session)

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
                vad=self.vad,
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
            session.analysis = analyst.analyze(resolved, session.analysis_style)
            self.sessions.write_json(session.id, "analysis.json", session.analysis)
            self.sessions.write_text(
                session.id,
                "analysis.md",
                analyst.to_markdown(session.analysis, session.analysis_style),
            )
            session.status = "done"
            session.stage_message = "已完成"
            self.sessions.save(session)
        except Exception as exc:
            self._fail(str(exc), session=session)

    def _validate_selected_speakers(self, profile_ids: list[str] | None) -> list[str]:
        if not isinstance(profile_ids, (list, tuple)):
            raise ValueError("参与者范围格式无效，请重新选择。")
        selected = list(dict.fromkeys(str(item).strip() for item in (profile_ids or []) if str(item).strip()))
        if not selected:
            raise ValueError("请至少选择一名已注册参与者。")
        registered = {profile.id for profile in self.profiles.load_all()}
        missing = [profile_id for profile_id in selected if profile_id not in registered]
        if missing:
            raise ValueError("选定参与者中包含未注册或已删除的声纹，请重新选择。")
        return selected

    def _profiles_for_session(self, session: SessionState):
        profiles = self.profiles.load_all()
        if not profiles:
            raise RuntimeError("请先注册至少一个声纹档案，再处理对话。")
        if not session.selected_speaker_ids:
            return profiles
        selected = set(session.selected_speaker_ids)
        scoped = [profile for profile in profiles if profile.id in selected]
        if len(scoped) != len(selected):
            raise RuntimeError("本次会话选定的参与者声纹已被删除，无法继续匹配。")
        return scoped

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
