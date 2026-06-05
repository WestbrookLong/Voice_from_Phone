from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import Literal


VoiceAgentStatus = Literal["idle", "recording", "polishing", "done", "failed"]


@dataclass
class VoiceAgentSession:
    id: str
    style: str = "formal_paragraph"
    status: VoiceAgentStatus = "idle"
    raw_transcript: str = ""
    polished_text: str = ""
    draft_text: str = ""
    error: str | None = None
    inserted: bool = False
    copied: bool = False
    audio_chunk_count: int = 0
    audio_byte_count: int = 0
    created_at: float = field(default_factory=time)
    updated_at: float = field(default_factory=time)

    def touch(self) -> None:
        self.updated_at = time()

    def snapshot(self) -> dict:
        return {
            "id": self.id,
            "style": self.style,
            "status": self.status,
            "rawTranscript": self.raw_transcript,
            "polishedText": self.polished_text,
            "draftText": self.draft_text,
            "error": self.error,
            "inserted": self.inserted,
            "copied": self.copied,
            "audioChunkCount": self.audio_chunk_count,
            "audioByteCount": self.audio_byte_count,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }
