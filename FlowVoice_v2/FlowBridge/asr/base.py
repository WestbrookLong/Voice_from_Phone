from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal


ASREventType = Literal["partial", "final", "error"]


@dataclass
class ASREvent:
    type: ASREventType
    text: str
    stable_text: str = ""
    unstable_text: str = ""
    error: str = ""


class StreamingASREngine(ABC):
    @abstractmethod
    def start(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def accept_audio(self, pcm: bytes) -> list[ASREvent]:
        raise NotImplementedError

    @abstractmethod
    def finalize(self) -> list[ASREvent]:
        raise NotImplementedError

    @abstractmethod
    def reset(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError

