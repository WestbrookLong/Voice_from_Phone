from __future__ import annotations

from .base import ASREvent, StreamingASREngine
from .funasr_offline_engine import extract_text
from .text_stability import split_stable_text


SAMPLE_RATE = 16000
DEFAULT_STREAMING_MODEL = "paraformer-zh-streaming"


class FunASRStreamingEngine(StreamingASREngine):
    def __init__(
        self,
        model_name: str = DEFAULT_STREAMING_MODEL,
        hotwords: str = "",
    ) -> None:
        self.model_name = model_name or DEFAULT_STREAMING_MODEL
        self.hotwords = hotwords.strip()
        self.model = None
        self.cache: dict = {}
        self.utterance_text = ""
        self.prev_partial = ""
        self.last_partial = ""
        self.available = True
        self.unavailable_reason = ""

    def start(self) -> None:
        try:
            from funasr import AutoModel

            try:
                self.model = AutoModel(model=self.model_name, disable_update=True)
            except TypeError:
                self.model = AutoModel(model=self.model_name)
        except Exception as exc:
            self.available = False
            self.unavailable_reason = str(exc)

    def accept_audio(self, pcm: bytes) -> list[ASREvent]:
        if not self.available:
            return [ASREvent(type="error", text="", error=f"FunASR streaming unavailable: {self.unavailable_reason}")]
        if self.model is None:
            return [ASREvent(type="error", text="", error="FunASR streaming model is not started.")]
        if not pcm:
            return []

        import numpy as np

        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        if audio.size == 0:
            return []

        generate_kwargs = {
            "input": audio,
            "cache": self.cache,
            "chunk_size": [0, 10, 5],
            "is_final": False,
            "fs": SAMPLE_RATE,
        }
        if self.hotwords:
            generate_kwargs["hotword"] = self.hotwords

        try:
            result = self.model.generate(**generate_kwargs)
        except Exception as exc:
            self.available = False
            self.unavailable_reason = str(exc)
            return [ASREvent(type="error", text="", error=f"FunASR streaming generate failed: {exc}")]

        text = self._merge_partial_text(extract_text(result))
        if not text:
            return []
        stable_text, unstable_text = split_stable_text(self.prev_partial, text)
        self.prev_partial = text
        self.last_partial = text
        return [
            ASREvent(
                type="partial",
                text=text,
                stable_text=stable_text,
                unstable_text=unstable_text,
            )
        ]

    def finalize(self) -> list[ASREvent]:
        if not self.available:
            self.reset()
            return []
        if self.model is None:
            self.reset()
            return [ASREvent(type="error", text="", error="FunASR streaming model is not started.")]

        try:
            result = self.model.generate(
                input=[],
                cache=self.cache,
                chunk_size=[0, 10, 5],
                is_final=True,
                fs=SAMPLE_RATE,
            )
            text = extract_text(result) or self.utterance_text or self.last_partial
        except Exception:
            text = self.utterance_text or self.last_partial

        self.reset()
        return [ASREvent(type="final", text=text)] if text else []

    def _merge_partial_text(self, update: str) -> str:
        update = update or ""
        if not update:
            return self.utterance_text
        if not self.utterance_text:
            self.utterance_text = update
            return self.utterance_text
        if update.startswith(self.utterance_text):
            self.utterance_text = update
            return self.utterance_text
        if self.utterance_text.endswith(update):
            return self.utterance_text

        prefix_len = 0
        limit = min(len(self.utterance_text), len(update))
        while prefix_len < limit and self.utterance_text[prefix_len] == update[prefix_len]:
            prefix_len += 1
        if prefix_len >= min(4, max(1, limit // 2)):
            self.utterance_text = update
        else:
            self.utterance_text += update
        return self.utterance_text

    def reset(self) -> None:
        self.cache = {}
        self.utterance_text = ""
        self.prev_partial = ""
        self.last_partial = ""

    def close(self) -> None:
        self.reset()
        self.model = None
