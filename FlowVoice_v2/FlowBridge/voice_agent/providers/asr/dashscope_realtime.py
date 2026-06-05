from __future__ import annotations

import os
import threading
from collections.abc import Callable


SentenceCallback = Callable[[str], None]
ErrorCallback = Callable[[str], None]


def _append_recognized_text(current: str, incoming: str) -> str:
    incoming = incoming.strip()
    if not incoming:
        return current
    if not current:
        return incoming
    if current.endswith(incoming):
        return current
    return f"{current}{incoming}"


class DashScopeRealtimeASRSession:
    def __init__(
        self,
        session_id: str,
        on_sentence: SentenceCallback,
        on_error: ErrorCallback,
    ) -> None:
        self.session_id = session_id
        self.on_sentence = on_sentence
        self.on_error = on_error
        self.lock = threading.RLock()
        self.recognition = None
        self.started = False
        self.stopped = False
        self.final_text = ""
        self.partial_text = ""
        self.error: str | None = None

    def start(self) -> None:
        try:
            import dashscope
            from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult
        except Exception as exc:
            raise RuntimeError(f"Missing DashScope ASR dependency: {exc}") from exc

        api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("DASHSCOPE_API_KEY is not configured.")
        dashscope.api_key = api_key

        owner = self

        class Callback(RecognitionCallback):
            def on_open(self) -> None:
                with owner.lock:
                    owner.started = True

            def on_error(self, result) -> None:
                message = getattr(result, "message", None) or str(result)
                owner._set_error(message)

            def on_event(self, result) -> None:
                sentence = result.get_sentence()
                text = str(sentence.get("text", "")).strip() if isinstance(sentence, dict) else ""
                if not text:
                    return
                with owner.lock:
                    owner.partial_text = text
                if RecognitionResult.is_sentence_end(sentence):
                    owner._handle_sentence_text(text)

        recognition = Recognition(
            model=os.environ.get("FLOWVOICE_ASR_MODEL", "paraformer-realtime-v2"),
            format="pcm",
            sample_rate=16000,
            language_hints=["zh", "en"],
            semantic_punctuation_enabled=False,
            callback=Callback(),
        )
        with self.lock:
            self.recognition = recognition
        recognition.start()

    def send_audio_frame(self, audio: bytes) -> None:
        if not audio:
            return
        with self.lock:
            recognition = self.recognition
            stopped = self.stopped
            error = self.error
        if stopped:
            return
        if error:
            raise RuntimeError(error)
        if recognition is None:
            raise RuntimeError("ASR recognition is not started.")
        recognition.send_audio_frame(audio)

    def stop(self) -> None:
        with self.lock:
            if self.stopped:
                return
            self.stopped = True
            recognition = self.recognition
            self.recognition = None
        if recognition is not None:
            recognition.stop()

    def _handle_sentence_text(self, text: str) -> None:
        with self.lock:
            if text == self.final_text or self.final_text.endswith(text):
                return
            self.final_text = _append_recognized_text(self.final_text, text)
        self.on_sentence(text)

    def _set_error(self, message: str) -> None:
        with self.lock:
            self.error = message
        self.on_error(message)
