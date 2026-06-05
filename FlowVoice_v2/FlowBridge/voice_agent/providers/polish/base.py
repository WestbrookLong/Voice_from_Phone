from __future__ import annotations

from abc import ABC, abstractmethod


class PolishProvider(ABC):
    name = "base"

    @abstractmethod
    def polish(self, transcript: str, style: str, glossary: str = "", incremental: bool = False) -> str:
        raise NotImplementedError
