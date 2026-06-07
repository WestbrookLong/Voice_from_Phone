from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TimedWord:
    id: str
    start_ms: int
    end_ms: int
    text: str
    punctuation: str = ""
    sentence_id: str = ""


@dataclass
class TranscriptSentence:
    id: str
    start_ms: int
    end_ms: int
    text: str
    words: list[TimedWord] = field(default_factory=list)


@dataclass
class AudioSegment:
    id: str
    start_ms: int
    end_ms: int
    audio_path: str
    text: str = ""
    change_point_before: bool = False


@dataclass
class SpeakerMatch:
    profile_id: str | None
    display_name: str
    score: float
    second_score: float
    margin: float
    accepted: bool
    confidence: str


@dataclass
class ResolvedUtterance:
    id: str
    canonical_speaker_id: str | None
    display_name: str
    start_ms: int
    end_ms: int
    text: str
    score: float = 0.0
    second_score: float = 0.0
    margin: float = 0.0
    confidence: str = "unknown"


@dataclass
class VoiceProfile:
    id: str
    name: str
    model_id: str
    sample_paths: list[str] = field(default_factory=list)
    embeddings: list[list[float]] = field(default_factory=list)
    centroid: list[float] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


@dataclass
class SessionState:
    id: str
    title: str
    status: str = "idle"
    stage_message: str = ""
    audio_path: str = ""
    speaker_mode: str = "two"
    task_id: str = ""
    uploaded_url: str = ""
    transcription_url: str = ""
    error: str | None = None
    transcript_sentences: list[dict[str, Any]] = field(default_factory=list)
    timed_words: list[dict[str, Any]] = field(default_factory=list)
    change_points: list[int] = field(default_factory=list)
    segments: list[dict[str, Any]] = field(default_factory=list)
    resolved_utterances: list[dict[str, Any]] = field(default_factory=list)
    analysis: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def touch(self) -> None:
        self.updated_at = utc_now()

    def snapshot(self) -> dict[str, Any]:
        return asdict(self)
