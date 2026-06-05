from __future__ import annotations

import secrets
import threading
from collections import deque
from typing import Callable

from .prompts import normalize_style
from .providers.asr import DashScopeRealtimeASRSession
from .providers.polish import BailianQwenPolishProvider, PreviewPolishProvider
from .providers.polish.base import PolishProvider
from .types import VoiceAgentSession


InsertCallback = Callable[[str], None]
CopyCallback = Callable[[str], None]


class VoiceAgentManager:
    def __init__(
        self,
        insert_callback: InsertCallback | None = None,
        copy_callback: CopyCallback | None = None,
        polish_provider: PolishProvider | None = None,
        max_sessions: int = 20,
    ) -> None:
        self.lock = threading.RLock()
        self.insert_callback = insert_callback
        self.copy_callback = copy_callback
        self.max_sessions = max_sessions
        self.sessions: dict[str, VoiceAgentSession] = {}
        self.audio_asr_sessions: dict[str, DashScopeRealtimeASRSession] = {}
        self.session_order: deque[str] = deque()
        self.active_session_id: str | None = None
        self.glossary = ""
        self.provider = polish_provider or self._default_provider()

    def _default_provider(self) -> PolishProvider:
        qwen = BailianQwenPolishProvider()
        if qwen.available():
            return qwen
        return PreviewPolishProvider()

    def provider_name(self) -> str:
        return getattr(self.provider, "name", "unknown")

    def start_session(self, style: str = "formal_paragraph") -> VoiceAgentSession:
        with self.lock:
            session_id = secrets.token_urlsafe(8)
            session = VoiceAgentSession(id=session_id, style=normalize_style(style), status="recording")
            self.sessions[session_id] = session
            self.session_order.append(session_id)
            self.active_session_id = session_id
            self._trim_sessions()
            return session

    def start_audio_session(self, style: str = "formal_paragraph") -> VoiceAgentSession:
        session = self.start_session(style)

        def on_sentence(text: str) -> None:
            self.append_transcript(session.id, text, replace=False, final=False)

        def on_error(message: str) -> None:
            self.fail_session(session.id, message)

        asr = DashScopeRealtimeASRSession(session.id, on_sentence=on_sentence, on_error=on_error)
        try:
            asr.start()
        except Exception as exc:
            return self.fail_session(session.id, str(exc))

        with self.lock:
            self.audio_asr_sessions[session.id] = asr
            return self.sessions[session.id]

    def append_transcript(
        self,
        session_id: str | None,
        text: str,
        *,
        replace: bool = False,
        final: bool = False,
    ) -> VoiceAgentSession:
        with self.lock:
            session = self._get_or_active(session_id)
            if replace:
                session.raw_transcript = text or ""
            else:
                session.raw_transcript = f"{session.raw_transcript}{text or ''}"
            session.status = "polishing" if final else "recording"
            session.error = None
            session.touch()

        return self._polish_session(session.id, incremental=not final, final=final)

    def append_audio_chunk(
        self,
        session_id: str | None,
        audio: bytes,
        *,
        transcript_text: str = "",
        final: bool = False,
    ) -> VoiceAgentSession:
        with self.lock:
            session = self._get_or_active(session_id)
            if audio:
                session.audio_chunk_count += 1
                session.audio_byte_count += len(audio)
            session.status = "polishing" if final else "recording"
            session.touch()
            asr = self.audio_asr_sessions.get(session.id)

        if audio and asr is not None:
            try:
                asr.send_audio_frame(audio)
            except Exception as exc:
                return self.fail_session(session.id, str(exc))

        if transcript_text:
            return self.append_transcript(session.id, transcript_text, replace=False, final=final)

        with self.lock:
            return self.sessions[session.id]

    def fail_session(self, session_id: str | None, message: str) -> VoiceAgentSession:
        with self.lock:
            session = self._get_or_active(session_id)
            session.status = "failed"
            session.error = message
            session.touch()
            return session

    def finalize_session(self, session_id: str | None = None, style: str | None = None) -> VoiceAgentSession:
        with self.lock:
            session = self._get_or_active(session_id)
            asr = self.audio_asr_sessions.pop(session.id, None)
            if style:
                session.style = normalize_style(style)
            session.status = "polishing"
            session.touch()
        if asr is not None:
            try:
                asr.stop()
            except Exception as exc:
                return self.fail_session(session.id, str(exc))
        return self._polish_session(session.id, incremental=False, final=True)

    def rerun_session(self, session_id: str | None = None, style: str | None = None) -> VoiceAgentSession:
        return self.finalize_session(session_id, style=style)

    def copy_result(self, session_id: str | None = None) -> VoiceAgentSession:
        with self.lock:
            session = self._get_or_active(session_id)
            text = session.polished_text or session.draft_text or session.raw_transcript
        if self.copy_callback is None:
            raise RuntimeError("Copy callback is not configured.")
        self.copy_callback(text)
        with self.lock:
            session.copied = True
            session.touch()
            return session

    def insert_result(self, session_id: str | None = None) -> VoiceAgentSession:
        with self.lock:
            session = self._get_or_active(session_id)
            text = session.polished_text or session.draft_text or session.raw_transcript
        if self.copy_callback is not None:
            self.copy_callback(text)
        if self.insert_callback is None:
            raise RuntimeError("Insert callback is not configured.")
        self.insert_callback(text)
        with self.lock:
            session.copied = True
            session.inserted = True
            session.touch()
            return session

    def get_state(self) -> dict:
        with self.lock:
            active = self.sessions.get(self.active_session_id or "")
            recent = [self.sessions[item].snapshot() for item in list(self.session_order)[-5:] if item in self.sessions]
            return {
                "provider": self.provider_name(),
                "configured": self.provider_name() != "preview",
                "activeSessionId": self.active_session_id,
                "activeSession": active.snapshot() if active else None,
                "recentSessions": recent,
            }

    def _polish_session(self, session_id: str, *, incremental: bool, final: bool) -> VoiceAgentSession:
        with self.lock:
            session = self.sessions[session_id]
            transcript = session.raw_transcript
            style = session.style
            glossary = self.glossary
        try:
            result = self.provider.polish(transcript, style, glossary=glossary, incremental=incremental)
        except Exception as exc:
            with self.lock:
                session = self.sessions[session_id]
                session.status = "failed"
                session.error = str(exc)
                session.touch()
                return session

        with self.lock:
            session = self.sessions[session_id]
            if final:
                session.polished_text = result
                session.draft_text = result
                session.status = "done"
            else:
                session.draft_text = result
                session.status = "recording"
            session.error = None
            session.touch()
            return session

    def _get_or_active(self, session_id: str | None) -> VoiceAgentSession:
        if session_id and session_id in self.sessions:
            return self.sessions[session_id]
        if self.active_session_id and self.active_session_id in self.sessions:
            return self.sessions[self.active_session_id]
        return self.start_session()

    def _trim_sessions(self) -> None:
        while len(self.session_order) > self.max_sessions:
            old_id = self.session_order.popleft()
            self.sessions.pop(old_id, None)
            old_asr = self.audio_asr_sessions.pop(old_id, None)
            if old_asr is not None:
                old_asr.stop()
