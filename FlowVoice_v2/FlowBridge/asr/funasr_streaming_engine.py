from __future__ import annotations

from .base import ASREvent, StreamingASREngine
from .funasr_offline_engine import extract_text
from .text_stability import split_stable_text


SAMPLE_RATE = 16000
DEFAULT_STREAMING_MODEL = "paraformer-zh-streaming"
DEFAULT_FINAL_MODEL = "iic/SenseVoiceSmall"


class FunASRStreamingEngine(StreamingASREngine):
    def __init__(
        self,
        model_name: str = DEFAULT_STREAMING_MODEL,
        hotwords: str = "",
        target_chunk_ms: int = 600,
    ) -> None:
        self.model_name = model_name or DEFAULT_STREAMING_MODEL
        self.hotwords = hotwords.strip()
        self.model = None
        self.final_model = None
        self.final_model_name = DEFAULT_FINAL_MODEL
        self.enable_final_rescore = True
        self.final_rescore_unavailable_reason = ""
        self.chunk_size = [5, 10, 5]
        self.target_chunk_ms = max(100, min(1000, int(target_chunk_ms or 600)))
        self.target_chunk_bytes = SAMPLE_RATE * self.target_chunk_ms // 1000 * 2
        self.cache: dict = {}
        self.utterance_text = ""
        self.prev_partial = ""
        self.last_partial = ""
        self.streaming_buffer = bytearray()
        self.full_audio_buffer = bytearray()
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
            return

        try:
            try:
                self.final_model = AutoModel(model=self.final_model_name, disable_update=True)
            except TypeError:
                self.final_model = AutoModel(model=self.final_model_name)
        except Exception as exc:
            self.final_model = None
            self.final_rescore_unavailable_reason = str(exc)

    def accept_audio(self, pcm: bytes) -> list[ASREvent]:
        if not self.available:
            return [ASREvent(type="error", text="", error=f"FunASR streaming unavailable: {self.unavailable_reason}")]
        if self.model is None:
            return [ASREvent(type="error", text="", error="FunASR streaming model is not started.")]
        if not pcm:
            return []

        self.full_audio_buffer.extend(pcm)
        self.streaming_buffer.extend(pcm)
        events: list[ASREvent] = []
        while len(self.streaming_buffer) >= self.target_chunk_bytes:
            chunk = bytes(self.streaming_buffer[: self.target_chunk_bytes])
            del self.streaming_buffer[: self.target_chunk_bytes]
            events.extend(self._generate_streaming_chunk(chunk, is_final=False))
        return events

    def _generate_streaming_chunk(self, pcm: bytes, is_final: bool) -> list[ASREvent]:
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
            "chunk_size": self.chunk_size,
            "is_final": is_final,
            "fs": SAMPLE_RATE,
        }
        if self.hotwords:
            generate_kwargs["hotword"] = self.hotwords

        try:
            result = self._generate_with_compat(self.model, generate_kwargs)
        except Exception:
            return []

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

        if self.streaming_buffer:
            self._generate_streaming_chunk(bytes(self.streaming_buffer), is_final=False)
            self.streaming_buffer.clear()

        streaming_final = ""
        try:
            result = self._generate_with_compat(
                self.model,
                {
                    "input": [],
                    "cache": self.cache,
                    "chunk_size": self.chunk_size,
                    "is_final": True,
                    "fs": SAMPLE_RATE,
                },
            )
            streaming_final = extract_text(result)
        except Exception:
            streaming_final = ""

        final_rescore_text = self._generate_final_rescore()
        text = final_rescore_text or streaming_final or self.last_partial

        self.reset()
        return [ASREvent(type="final", text=text)] if text else []

    def _generate_final_rescore(self) -> str:
        if not self.enable_final_rescore or self.final_model is None or not self.full_audio_buffer:
            return ""

        import numpy as np

        audio = np.frombuffer(bytes(self.full_audio_buffer), dtype=np.int16).astype(np.float32) / 32768.0
        if audio.size == 0:
            return ""

        generate_kwargs = {
            "input": audio,
            "fs": SAMPLE_RATE,
            "language": "auto",
            "use_itn": True,
            "batch_size_s": 60,
        }
        if self.hotwords:
            generate_kwargs["hotword"] = self.hotwords

        removable_keys = ["language", "use_itn", "fs", "hotword"]
        for remove_count in range(0, len(removable_keys) + 1):
            attempt_kwargs = dict(generate_kwargs)
            for key in removable_keys[:remove_count]:
                attempt_kwargs.pop(key, None)
            try:
                return extract_text(self.final_model.generate(**attempt_kwargs))
            except TypeError:
                continue
            except Exception as exc:
                self.final_rescore_unavailable_reason = str(exc)
                return ""
        return ""

    def _generate_with_compat(self, model, generate_kwargs: dict):
        removable_keys = ["hotword", "fs"]
        for remove_count in range(0, len(removable_keys) + 1):
            attempt_kwargs = dict(generate_kwargs)
            for key in removable_keys[:remove_count]:
                attempt_kwargs.pop(key, None)
            try:
                return model.generate(**attempt_kwargs)
            except TypeError:
                continue
        return model.generate(**generate_kwargs)

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
        self.streaming_buffer = bytearray()
        self.full_audio_buffer = bytearray()

    def close(self) -> None:
        self.reset()
        self.model = None
        self.final_model = None
