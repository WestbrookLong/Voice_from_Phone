import asyncio
import ctypes
import os
import queue
import secrets
import sys
import threading
import time
import webbrowser
from pathlib import Path

from aiohttp import web
import webview

from asr.base import ASREvent, StreamingASREngine
from asr.bert_reranker import DEFAULT_BERT_RERANKER_MODEL
from asr.endpointing import EndpointConfig, EndpointDecision, EndpointDetector
from asr.funasr_candidate_streaming_engine import FunASRCandidateStreamingEngine
from asr.funasr_offline_engine import FunASROfflineEngine
from asr.funasr_streaming_engine import DEFAULT_STREAMING_MODEL, FunASRStreamingEngine
from asr.punctuation import PunctuationEngine
from asr.vosk_engine import VoskEngine
from server import BridgeSettings, FlowInputSession, create_app, get_lan_ip, log, render_text, send_backspace_chunks, type_text


DESKTOP_VOICE_MODEL_NAME = "vosk-model-small-cn-0.22"
DESKTOP_VOICE_DEFAULT_CONFIG = {
    "engine": "vosk",
    "funasrMode": "offline",
    "funasrModel": "iic/SenseVoiceSmall",
    "funasrStreamingChunkMs": 600,
    "semanticReranker": "bert",
    "semanticModel": DEFAULT_BERT_RERANKER_MODEL,
    "punctuationStrategy": "spoken",
    "voiceCommands": True,
    "hotwords": "",
}
VALID_DESKTOP_VOICE_ENGINES = {"vosk", "funasr"}
VALID_FUNASR_MODELS = {"iic/SenseVoiceSmall", "paraformer-zh"}
VALID_FUNASR_MODES = {"offline", "streaming", "candidate_streaming"}
VALID_SEMANTIC_RERANKERS = {"bert", "heuristic"}
VALID_PUNCTUATION_STRATEGIES = {"spoken", "model", "none"}
DESKTOP_VOICE_VIRTUAL_RESET_CHARS = 50


def app_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def ui_index_path() -> Path:
    return app_root() / "desktop_ui" / "dist" / "index.html"


def ui_url() -> str:
    dev_url = os.environ.get("FLOWBRIDGE_UI_DEV_URL")
    if dev_url:
        return dev_url

    index_path = ui_index_path()
    if not index_path.exists():
        raise SystemExit(f"React desktop UI is not built: {index_path}")
    return index_path.as_uri()


def desktop_voice_model_path() -> Path:
    configured = os.environ.get("FLOWVOICE_VOSK_MODEL")
    if configured:
        return Path(configured).expanduser().resolve()
    return app_root() / "models" / DESKTOP_VOICE_MODEL_NAME


def should_insert_space(left: str, right: str) -> bool:
    return bool(left and right and left[-1].isascii() and right[0].isascii() and left[-1].isalnum() and right[0].isalnum())


def append_recognized_text(base: str, addition: str) -> str:
    if not addition:
        return base
    if should_insert_space(base, addition):
        return f"{base} {addition}"
    return f"{base}{addition}"


def normalize_desktop_voice_config(value: dict | None) -> dict:
    source = value if isinstance(value, dict) else {}
    config = dict(DESKTOP_VOICE_DEFAULT_CONFIG)
    engine = str(source.get("engine", config["engine"])).strip().lower()
    if engine in VALID_DESKTOP_VOICE_ENGINES:
        config["engine"] = engine

    funasr_mode = str(source.get("funasrMode", config["funasrMode"])).strip().lower()
    if funasr_mode in VALID_FUNASR_MODES:
        config["funasrMode"] = funasr_mode

    funasr_model = str(source.get("funasrModel", config["funasrModel"])).strip()
    if funasr_model in VALID_FUNASR_MODELS:
        config["funasrModel"] = funasr_model
    if config["engine"] == "funasr" and config["funasrMode"] in {"streaming", "candidate_streaming"}:
        config["funasrStreamingModel"] = DEFAULT_STREAMING_MODEL
    try:
        streaming_chunk_ms = int(source.get("funasrStreamingChunkMs", config["funasrStreamingChunkMs"]))
    except (TypeError, ValueError):
        streaming_chunk_ms = config["funasrStreamingChunkMs"]
    config["funasrStreamingChunkMs"] = max(100, min(1000, streaming_chunk_ms))

    semantic_reranker = str(source.get("semanticReranker", config["semanticReranker"])).strip().lower()
    if semantic_reranker in VALID_SEMANTIC_RERANKERS:
        config["semanticReranker"] = semantic_reranker
    semantic_model = str(source.get("semanticModel", config["semanticModel"])).strip()
    config["semanticModel"] = semantic_model or DEFAULT_BERT_RERANKER_MODEL

    punctuation_strategy = str(source.get("punctuationStrategy", config["punctuationStrategy"])).strip().lower()
    if punctuation_strategy in VALID_PUNCTUATION_STRATEGIES:
        config["punctuationStrategy"] = punctuation_strategy

    config["voiceCommands"] = bool(source.get("voiceCommands", config["voiceCommands"]))
    config["hotwords"] = str(source.get("hotwords", config["hotwords"])).strip()
    return config


def bridge_settings_from_desktop_config(config: dict) -> BridgeSettings:
    use_spoken_punctuation = config.get("punctuationStrategy") == "spoken"
    return BridgeSettings(
        filter_punctuation=use_spoken_punctuation,
        convert_spoken_punctuation=use_spoken_punctuation,
        enable_voice_commands=bool(config.get("voiceCommands", True)),
    )


def create_asr_engine(config: dict, model_path: Path) -> StreamingASREngine:
    if config["engine"] == "vosk":
        return VoskEngine(model_path)
    if config.get("funasrMode") == "candidate_streaming":
        return FunASRCandidateStreamingEngine(
            DEFAULT_STREAMING_MODEL,
            hotwords=config.get("hotwords", ""),
            target_chunk_ms=config.get("funasrStreamingChunkMs", 600),
            semantic_reranker=config.get("semanticReranker", "bert"),
            semantic_model=config.get("semanticModel", DEFAULT_BERT_RERANKER_MODEL),
        )
    if config.get("funasrMode") == "streaming":
        return FunASRStreamingEngine(
            DEFAULT_STREAMING_MODEL,
            hotwords=config.get("hotwords", ""),
            target_chunk_ms=config.get("funasrStreamingChunkMs", 600),
        )
    return FunASROfflineEngine(
        model_name=config["funasrModel"],
        punctuation_strategy=config["punctuationStrategy"],
        hotwords=config.get("hotwords", ""),
    )


def copy_text_to_clipboard(text: str) -> None:
    if sys.platform != "win32":
        raise RuntimeError("Clipboard copy is only implemented for Windows.")

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002

    if not user32.OpenClipboard(None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not user32.EmptyClipboard():
            raise ctypes.WinError(ctypes.get_last_error())

        buffer = ctypes.create_unicode_buffer(text)
        size = ctypes.sizeof(buffer)
        kernel32.GlobalAlloc.argtypes = (ctypes.c_uint, ctypes.c_size_t)
        kernel32.GlobalAlloc.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = (ctypes.c_void_p,)
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = (ctypes.c_void_p,)
        user32.SetClipboardData.argtypes = (ctypes.c_uint, ctypes.c_void_p)
        user32.SetClipboardData.restype = ctypes.c_void_p
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())

        locked = kernel32.GlobalLock(handle)
        if not locked:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            ctypes.memmove(locked, buffer, size)
        finally:
            kernel32.GlobalUnlock(handle)

        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        user32.CloseClipboard()


class BridgeServerThread(threading.Thread):
    def __init__(self, host: str, port: int, token: str) -> None:
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        self.token = token
        self.loop: asyncio.AbstractEventLoop | None = None
        self.runner: web.AppRunner | None = None
        self.ready = threading.Event()
        self.error: str | None = None

    def run(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._start())
            self.ready.set()
            self.loop.run_forever()
        except Exception as exc:
            self.error = str(exc)
            self.ready.set()
        finally:
            self.loop.run_until_complete(self._cleanup())
            self.loop.close()

    async def _start(self) -> None:
        app = create_app(self.token)
        self.runner = web.AppRunner(app, access_log=None)
        await self.runner.setup()
        site = web.TCPSite(self.runner, self.host, self.port)
        await site.start()

    async def _cleanup(self) -> None:
        if self.runner is not None:
            await self.runner.cleanup()

    def stop(self) -> None:
        if self.loop is not None:
            self.loop.call_soon_threadsafe(self.loop.stop)


class DesktopVoiceThread(threading.Thread):
    def __init__(self, model_path: Path, settings: BridgeSettings, config: dict) -> None:
        super().__init__(daemon=True)
        self.model_path = model_path
        self.settings = settings
        self.config = normalize_desktop_voice_config(config)
        self.session = FlowInputSession()
        self.asr_engine: StreamingASREngine | None = None
        self.punctuation_engine: PunctuationEngine | None = None
        self.audio_queue: queue.Queue[bytes] = queue.Queue(maxsize=32)
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.ready = threading.Event()
        self.lock = threading.RLock()
        self.audio_drop_count = 0
        self.audio_total_drop_count = 0
        self.error: str | None = None
        self.status = "STARTING"
        self.endpoint_status: dict = {}
        self.committed_text = ""
        self.pending_partial_text = ""
        self.composition_text = ""
        self.committed_partial_text = ""
        self.composition_tail_chars = 6
        self.latest_rescore_utterance_id = 0

    def snapshot(self) -> dict:
        with self.lock:
            running = self.is_alive() and self.error is None and not self.stop_event.is_set()
            return {
                "running": running,
                "paused": self.pause_event.is_set(),
                "status": self.status,
                "error": self.error,
                "modelPath": str(self.model_path),
                "engine": self.config["engine"],
                "funasrMode": self.config["funasrMode"],
                "funasrModel": self.config["funasrModel"],
                "activeModel": self._active_model_name(),
                "finalRescoreModel": self._final_rescore_model_name(),
                "streamingChunkMs": self.config.get("funasrStreamingChunkMs", 600),
                "endpoint": dict(self.endpoint_status),
            }

    def set_status(self, status: str) -> None:
        with self.lock:
            self.status = status

    def set_error(self, message: str) -> None:
        with self.lock:
            self.error = message
            self.status = "ERROR"

    def run(self) -> None:
        try:
            self._run_recognizer()
        except Exception as exc:
            self.set_error(str(exc))
            self.ready.set()
        finally:
            if self._uses_ime_composition():
                self._clear_composition()
                self._reset_streaming_text_state()
            self.session.reset()
            if self.asr_engine is not None:
                self.asr_engine.close()
            if self.punctuation_engine is not None:
                self.punctuation_engine.close()
            if self.error is None:
                self.set_status("STOPPED")

    def _run_recognizer(self) -> None:
        try:
            import sounddevice as sd
        except Exception as exc:
            self.set_error(f"Missing desktop voice dependency: {exc}")
            self.ready.set()
            return

        try:
            self.set_status(self._loading_status())
            self.asr_engine = create_asr_engine(self.config, self.model_path)
            self.asr_engine.start()
            self.punctuation_engine = PunctuationEngine(self.config["punctuationStrategy"])
            self.punctuation_engine.start()
        except Exception as exc:
            self.set_error(str(exc))
            self.ready.set()
            return

        sample_rate = 16000
        blocksize = 8000 if self.config["engine"] == "vosk" else 1600

        def audio_callback(indata, frames, time_info, status) -> None:
            if status:
                self.set_status(f"AUDIO WARNING: {status}")
            try:
                self.audio_queue.put_nowait(bytes(indata))
            except queue.Full:
                self._record_audio_drop()

        self.set_status("LISTENING")
        self.ready.set()
        endpoint_detector = EndpointDetector(
            EndpointConfig(
                sample_rate=sample_rate,
                frame_ms=max(1, int(blocksize * 1000 / sample_rate)),
            )
        )

        with sd.RawInputStream(
            samplerate=sample_rate,
            blocksize=blocksize,
            dtype="int16",
            channels=1,
            callback=audio_callback,
        ):
            while not self.stop_event.is_set():
                self._poll_asr_events()
                try:
                    data = self.audio_queue.get(timeout=0.1)
                except queue.Empty:
                    self._poll_asr_events()
                    continue

                if self.pause_event.is_set():
                    self._discard_paused_audio()
                    endpoint_detector.reset()
                    continue

                if self.config["engine"] == "vosk":
                    drops = self._consume_audio_drops()
                    if drops:
                        log(f"[endpoint] audio queue dropped {drops} frame(s) while using vosk")
                    self._handle_asr_events(self.asr_engine.accept_audio(data))
                    continue

                drops = self._consume_audio_drops()
                if drops:
                    drop_decision = endpoint_detector.handle_dropped_frames(drops)
                    self._update_endpoint_status(drop_decision)
                    log(f"[endpoint] audio queue dropped {drops} frame(s), state={drop_decision.state}")
                    if drop_decision.reset_asr:
                        self._handle_endpoint_reset(drop_decision)
                        continue

                decision = endpoint_detector.process(data)
                self._update_endpoint_status(decision)
                self._handle_endpoint_decision(decision)

    def _handle_endpoint_decision(self, decision: EndpointDecision) -> None:
        if decision.started:
            log(
                "[endpoint] speech start "
                f"snr={decision.features.snr_db:.1f}dB noise={decision.features.noise_rms:.1f} "
                f"rms={decision.features.rms:.1f}"
            )

        for chunk in decision.frames:
            self._handle_asr_events(self.asr_engine.accept_audio(chunk))

        if not decision.endpoint:
            return

        log(
            "[endpoint] speech end "
            f"reason={decision.reason} snr={decision.features.snr_db:.1f}dB "
            f"noise={decision.features.noise_rms:.1f} dropped={decision.dropped_frames}"
        )
        if decision.too_short or decision.reset_asr:
            self._handle_endpoint_reset(decision)
            return

        self.set_status("RECOGNIZING")
        self._handle_asr_events(self.asr_engine.finalize())
        self.set_status("LISTENING")

    def _handle_endpoint_reset(self, decision: EndpointDecision) -> None:
        if self._uses_ime_composition():
            self._discard_streaming_partial()
        if self.asr_engine is not None:
            self.asr_engine.reset()
        self.set_status("LISTENING")
        log(f"[endpoint] reset ASR reason={decision.reason}")

    def _update_endpoint_status(self, decision: EndpointDecision) -> None:
        with self.lock:
            self.endpoint_status = {
                "state": decision.state,
                "reason": decision.reason,
                "noiseRms": round(decision.features.noise_rms, 2),
                "rms": round(decision.features.rms, 2),
                "snrDb": round(decision.features.snr_db, 2),
                "dropCount": self.audio_drop_count,
                "totalDropCount": self.audio_total_drop_count,
            }

    def _record_audio_drop(self) -> None:
        with self.lock:
            self.audio_drop_count += 1
            self.audio_total_drop_count += 1

    def _consume_audio_drops(self) -> int:
        with self.lock:
            drops = self.audio_drop_count
            self.audio_drop_count = 0
            return drops

    def _loading_status(self) -> str:
        if self.config["engine"] == "vosk":
            return "LOADING MODEL"
        if self.config.get("funasrMode") == "candidate_streaming":
            return "LOADING FUNASR CANDIDATE STREAMING"
        if self.config.get("funasrMode") == "streaming":
            return "LOADING FUNASR STREAMING"
        return "LOADING FUNASR"

    def _active_model_name(self) -> str:
        if self.config["engine"] == "vosk":
            return "vosk"
        if self.config.get("funasrMode") in {"streaming", "candidate_streaming"}:
            return DEFAULT_STREAMING_MODEL
        return self.config["funasrModel"]

    def _final_rescore_model_name(self) -> str:
        if self.config["engine"] == "funasr" and self.config.get("funasrMode") == "streaming":
            return "iic/SenseVoiceSmall"
        if self.config["engine"] == "funasr" and self.config.get("funasrMode") == "candidate_streaming":
            if self.config.get("semanticReranker") == "bert":
                return self.config.get("semanticModel", DEFAULT_BERT_RERANKER_MODEL)
            return "candidate heuristic reranker"
        return ""

    def _discard_paused_audio(self) -> None:
        if self._uses_ime_composition():
            self._discard_streaming_partial()
        self.pending_partial_text = ""
        self.committed_text = ""
        self._reset_streaming_text_state()
        self.session.reset()
        if self.asr_engine is not None:
            self.asr_engine.reset()
        while True:
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                break

    def _handle_asr_events(self, events: list[ASREvent]) -> None:
        if self._uses_ime_composition():
            self._handle_ime_asr_events(events)
            return

        for event in events:
            if event.type == "error":
                self.set_error(event.error or event.text or "ASR engine error")
                continue
            if event.type == "partial":
                partial = self._select_partial(event.text)
                self.pending_partial_text = partial
                self.session.sync_state(append_recognized_text(self.committed_text, partial), self.settings)
                continue
            if event.type == "final":
                text = event.text
                if self.punctuation_engine is not None:
                    text = self.punctuation_engine.apply_final(text)
                self.pending_partial_text = ""
                if text:
                    self.committed_text = append_recognized_text(self.committed_text, text)
                    self.session.sync_state(self.committed_text, self.settings)
                    self._reset_virtual_input_window_if_needed()

    def _select_partial(self, new_text: str) -> str:
        old = self.pending_partial_text
        if not old:
            return new_text
        if new_text.startswith(old):
            return new_text
        if len(new_text) + 2 < len(old):
            return old
        return new_text

    def _uses_ime_composition(self) -> bool:
        return self.config["engine"] == "funasr" and self.config.get("funasrMode") in {
            "streaming",
            "candidate_streaming",
        }

    def _handle_ime_asr_events(self, events: list[ASREvent]) -> None:
        for event in events:
            if event.type == "error":
                self._discard_streaming_partial()
                self._reset_streaming_text_state()
                self.set_error(event.error or event.text or "ASR engine error")
                continue
            if event.type == "partial":
                self._handle_streaming_virtual_partial(event)
                continue
            if event.type == "final":
                if event.source == "final_rescore":
                    self._handle_streaming_virtual_rescore(event)
                    continue
                self._handle_streaming_virtual_final(event)

    def _replace_composition(self, text: str) -> None:
        old = self.composition_text
        new = text or ""
        prefix_len = self._common_prefix_len(old, new)
        delete_count = len(old) - prefix_len
        append_text = new[prefix_len:]

        if delete_count:
            send_backspace_chunks(delete_count)
        if append_text:
            type_text(append_text)
        self.composition_text = new

    def _clear_composition(self) -> None:
        if self.composition_text:
            send_backspace_chunks(len(self.composition_text))
            self.composition_text = ""

    def _handle_streaming_virtual_partial(self, event: ASREvent) -> None:
        partial = event.text or ""
        if not partial:
            return
        self.pending_partial_text = partial
        self.session.sync_state(append_recognized_text(self.committed_text, partial), self.settings)

    def _handle_streaming_virtual_final(self, event: ASREvent) -> None:
        text = event.text
        if event.source == "streaming_final" and event.utterance_id:
            self.latest_rescore_utterance_id = event.utterance_id
        if self.punctuation_engine is not None:
            text = self.punctuation_engine.apply_final(text)

        if text:
            self.committed_text = append_recognized_text(self.committed_text, text)
            self.pending_partial_text = ""
            self.session.sync_state(self.committed_text, self.settings)
            self._reset_virtual_input_window_if_needed()
            return

        if self.pending_partial_text:
            self.committed_text = append_recognized_text(self.committed_text, self.pending_partial_text)
            self.pending_partial_text = ""
            self._reset_virtual_input_window_if_needed()

    def _handle_streaming_virtual_rescore(self, event: ASREvent) -> None:
        if event.utterance_id and event.utterance_id != self.latest_rescore_utterance_id:
            return
        original_text = event.stable_text or ""
        text = event.text
        if self.punctuation_engine is not None:
            text = self.punctuation_engine.apply_final(text)
        if not original_text or not text:
            return
        if not self.committed_text.endswith(original_text):
            return
        prefix = self.committed_text[: -len(original_text)]
        next_committed_text = append_recognized_text(prefix, text) if prefix else text
        if next_committed_text == self.committed_text:
            return
        self.committed_text = next_committed_text
        self.pending_partial_text = ""
        self.session.sync_state(self.committed_text, self.settings)
        self._reset_virtual_input_window_if_needed()

    def _discard_streaming_partial(self) -> None:
        self._clear_composition()
        if self.pending_partial_text:
            self.session.sync_state(self.committed_text, self.settings)
            self.pending_partial_text = ""

    def _handle_streaming_partial(self, event: ASREvent) -> None:
        full = render_text(event.text, self.settings)
        stable = render_text(event.stable_text, self.settings)
        if not full:
            return

        committed_target = stable if full.startswith(stable) else ""
        if len(full) > self.composition_tail_chars:
            forced_target = full[:-self.composition_tail_chars]
            if len(forced_target) > len(committed_target):
                committed_target = forced_target

        if self.committed_partial_text and not full.startswith(self.committed_partial_text):
            self._replace_composition(full[-self.composition_tail_chars :])
            return

        if len(committed_target) < len(self.committed_partial_text):
            committed_target = self.committed_partial_text

        newly_committed = committed_target[len(self.committed_partial_text) :]
        if newly_committed:
            self._clear_composition()
            type_text(newly_committed)
            self.committed_partial_text = committed_target

        composition_target = full[len(self.committed_partial_text) :]
        if len(composition_target) > self.composition_tail_chars:
            composition_target = composition_target[-self.composition_tail_chars :]
        self._replace_composition(composition_target)

    def _handle_streaming_final(self, event: ASREvent) -> None:
        text = event.text
        if self.punctuation_engine is not None:
            text = self.punctuation_engine.apply_final(text)
        final_text = render_text(text, self.settings)

        self._clear_composition()
        if not final_text:
            self._reset_streaming_text_state()
            return

        if not self.committed_partial_text:
            final_session = FlowInputSession()
            final_session.sync_state(final_text, self.settings)
        elif final_text.startswith(self.committed_partial_text):
            remaining = final_text[len(self.committed_partial_text) :]
            if remaining:
                final_session = FlowInputSession()
                final_session.sync_state(remaining, self.settings)

        self._reset_streaming_text_state()

    def _common_prefix_len(self, left: str, right: str) -> int:
        limit = min(len(left), len(right))
        index = 0
        while index < limit and left[index] == right[index]:
            index += 1
        return index

    def _reset_streaming_text_state(self) -> None:
        self.committed_partial_text = ""
        self.composition_text = ""
        self.latest_rescore_utterance_id = 0

    def _reset_virtual_input_window_if_needed(self) -> None:
        if len(self.committed_text) < DESKTOP_VOICE_VIRTUAL_RESET_CHARS:
            return
        self.committed_text = ""
        self.pending_partial_text = ""
        self.session.reset()

    def _poll_asr_events(self) -> None:
        if self.asr_engine is None:
            return
        self._handle_asr_events(self.asr_engine.poll_events())

    def stop(self) -> None:
        self.stop_event.set()

    def pause(self) -> None:
        self.pause_event.set()
        self.set_status("PAUSED")
        self._discard_paused_audio()

    def resume(self) -> None:
        self._discard_paused_audio()
        self.pause_event.clear()
        self.set_status("LISTENING")


class DesktopApi:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.lan_ip = get_lan_ip()
        self.page_version = str(int(time.time()))
        self.token = secrets.token_urlsafe(12)
        self.port = "8787"
        self.server_thread: BridgeServerThread | None = None
        self.desktop_voice_thread: DesktopVoiceThread | None = None
        self.desktop_voice_config = normalize_desktop_voice_config(None)
        self.desktop_voice_settings = bridge_settings_from_desktop_config(self.desktop_voice_config)
        self.window: webview.Window | None = None
        self.maximized = False

    def _url(self) -> str:
        return f"http://{self.lan_ip}:{self.port}/?token={self.token}&v={self.page_version}"

    def _running(self) -> bool:
        return self.server_thread is not None and self.server_thread.error is None

    def _desktop_voice_running(self) -> bool:
        return (
            self.desktop_voice_thread is not None
            and self.desktop_voice_thread.is_alive()
            and self.desktop_voice_thread.error is None
            and not self.desktop_voice_thread.stop_event.is_set()
        )

    def _desktop_voice_settings_snapshot(self) -> dict:
        return dict(self.desktop_voice_config)

    def _desktop_voice_final_rescore_model_name(self) -> str:
        if self.desktop_voice_config["engine"] != "funasr":
            return ""
        if self.desktop_voice_config["funasrMode"] == "streaming":
            return "iic/SenseVoiceSmall"
        if self.desktop_voice_config["funasrMode"] == "candidate_streaming":
            if self.desktop_voice_config.get("semanticReranker") == "bert":
                return self.desktop_voice_config.get("semanticModel", DEFAULT_BERT_RERANKER_MODEL)
            return "candidate heuristic reranker"
        return ""

    def _result(self, message: str = "") -> dict:
        return {"state": self.get_state(), "message": message}

    def get_state(self) -> dict:
        with self.lock:
            running = self._running()
            voice_snapshot = (
                self.desktop_voice_thread.snapshot()
                if self.desktop_voice_thread is not None
                else {
                    "running": False,
                    "paused": False,
                    "status": "STOPPED",
                    "error": None,
                    "modelPath": str(desktop_voice_model_path()),
                    "engine": self.desktop_voice_config["engine"],
                    "funasrMode": self.desktop_voice_config["funasrMode"],
                    "funasrModel": self.desktop_voice_config["funasrModel"],
                    "activeModel": DEFAULT_STREAMING_MODEL if self.desktop_voice_config["engine"] == "funasr" and self.desktop_voice_config["funasrMode"] in {"streaming", "candidate_streaming"} else self.desktop_voice_config["funasrModel"],
                    "finalRescoreModel": self._desktop_voice_final_rescore_model_name(),
                    "streamingChunkMs": self.desktop_voice_config.get("funasrStreamingChunkMs", 600),
                }
            )
            return {
                "running": running,
                "token": self.token,
                "ip": self.lan_ip,
                "port": self.port,
                "url": self._url(),
                "status": "SERVICE STARTED" if running else "SERVICE STOPPED",
                "desktopVoice": voice_snapshot,
                "desktopVoiceSettings": self._desktop_voice_settings_snapshot(),
            }

    def set_port(self, value: str) -> dict:
        with self.lock:
            if self._running():
                return self._result("Stop the service before changing the port.")
            cleaned = "".join(ch for ch in str(value) if ch.isdigit())[:5]
            self.port = cleaned or "8787"
            return self._result()

    def set_token(self, value: str) -> dict:
        with self.lock:
            if self._running():
                return self._result("Stop the service before changing the token.")
            self.token = str(value).strip() or secrets.token_urlsafe(12)
            return self._result()

    def regenerate_token(self) -> dict:
        with self.lock:
            if self._running():
                return self._result("Stop the service before regenerating the token.")
            self.token = secrets.token_urlsafe(12)
            return self._result("New token generated.")

    def start_service(self) -> dict:
        with self.lock:
            if self._running():
                return self._result("Service is already running.")
            try:
                port = int(self.port)
                if port <= 0 or port > 65535:
                    raise ValueError
            except ValueError:
                return self._result("Port must be between 1 and 65535.")

            thread = BridgeServerThread("0.0.0.0", port, self.token)
            self.server_thread = thread
            thread.start()

        thread.ready.wait(timeout=4)

        with self.lock:
            if thread.error:
                self.server_thread = None
                return self._result(f"Failed to start service: {thread.error}")
            return self._result("Service started.")

    def stop_service(self) -> dict:
        with self.lock:
            thread = self.server_thread
            self.server_thread = None
        if thread is not None:
            thread.stop()
            thread.join(timeout=2)
        return self._result("Service stopped.")

    def copy_url(self) -> dict:
        url = self.get_state()["url"]
        try:
            copy_text_to_clipboard(url)
            return self._result("URL copied to clipboard.")
        except Exception as exc:
            return self._result(f"Clipboard copy failed: {exc}")

    def open_url(self) -> dict:
        webbrowser.open(self.get_state()["url"])
        return self._result("Opened the voice input page.")

    def start_desktop_voice(self) -> dict:
        with self.lock:
            if self._desktop_voice_running():
                return self._result("Desktop voice is already listening.")
            thread = DesktopVoiceThread(desktop_voice_model_path(), self.desktop_voice_settings, self.desktop_voice_config)
            self.desktop_voice_thread = thread
            thread.start()

        thread.ready.wait(timeout=8)

        with self.lock:
            if thread.error:
                return self._result(f"Failed to start desktop voice: {thread.error}")
            return self._result("Desktop voice started.")

    def stop_desktop_voice(self) -> dict:
        with self.lock:
            thread = self.desktop_voice_thread
            self.desktop_voice_thread = None
        if thread is not None:
            thread.stop()
            thread.join(timeout=2)
        return self._result("Desktop voice stopped.")

    def pause_desktop_voice(self) -> dict:
        with self.lock:
            thread = self.desktop_voice_thread
            if thread is None or not self._desktop_voice_running():
                return self._result("Desktop voice is not running.")
            thread.pause()
            return self._result("Desktop voice paused.")

    def resume_desktop_voice(self) -> dict:
        with self.lock:
            thread = self.desktop_voice_thread
            if thread is None or not self._desktop_voice_running():
                return self._result("Desktop voice is not running.")
            thread.resume()
            return self._result("Desktop voice resumed.")

    def set_desktop_voice_settings(self, value: dict) -> dict:
        with self.lock:
            previous_engine = self.desktop_voice_config["engine"]
            previous_mode = self.desktop_voice_config["funasrMode"]
            previous_model = self.desktop_voice_config["funasrModel"]
            previous_chunk_ms = self.desktop_voice_config.get("funasrStreamingChunkMs", 600)
            previous_hotwords = self.desktop_voice_config.get("hotwords", "")
            previous_reranker = self.desktop_voice_config.get("semanticReranker", "bert")
            previous_semantic_model = self.desktop_voice_config.get("semanticModel", DEFAULT_BERT_RERANKER_MODEL)
            self.desktop_voice_config = normalize_desktop_voice_config(value)
            next_settings = bridge_settings_from_desktop_config(self.desktop_voice_config)
            self.desktop_voice_settings.filter_punctuation = next_settings.filter_punctuation
            self.desktop_voice_settings.convert_spoken_punctuation = next_settings.convert_spoken_punctuation
            self.desktop_voice_settings.enable_voice_commands = next_settings.enable_voice_commands
            needs_restart = self._desktop_voice_running() and (
                previous_engine != self.desktop_voice_config["engine"]
                or previous_mode != self.desktop_voice_config["funasrMode"]
                or previous_model != self.desktop_voice_config["funasrModel"]
                or previous_chunk_ms != self.desktop_voice_config.get("funasrStreamingChunkMs", 600)
                or previous_hotwords != self.desktop_voice_config.get("hotwords", "")
                or previous_reranker != self.desktop_voice_config.get("semanticReranker", "bert")
                or previous_semantic_model != self.desktop_voice_config.get("semanticModel", DEFAULT_BERT_RERANKER_MODEL)
            )
            if needs_restart:
                return self._result("Settings saved. Restart desktop voice to apply model or hotword changes.")
            return self._result("Desktop voice settings updated.")

    def minimize_window(self) -> dict:
        if self.window is not None:
            self.window.minimize()
        return self._result()

    def toggle_maximize_window(self) -> dict:
        if self.window is not None:
            if self.maximized:
                self.window.restore()
                self.maximized = False
            else:
                self.window.maximize()
                self.maximized = True
        return self._result()

    def close_window(self) -> dict:
        state = self._result("Closing...")

        def destroy_later() -> None:
            self.shutdown()
            if self.window is not None:
                self.window.destroy()

        threading.Timer(0.05, destroy_later).start()
        return state

    def shutdown(self) -> None:
        self.stop_desktop_voice()
        self.stop_service()


def apply_window_chrome(window: webview.Window) -> None:
    if sys.platform != "win32":
        return
    try:
        hwnd = ctypes.c_void_p(window.native.Handle.ToInt64())
        dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)

        def colorref(hex_color: str) -> int:
            value = hex_color.lstrip("#")
            red = int(value[0:2], 16)
            green = int(value[2:4], 16)
            blue = int(value[4:6], 16)
            return red | (green << 8) | (blue << 16)

        def set_dwm_attribute(attribute: int, value: int) -> None:
            data = ctypes.c_int(value)
            dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(data), ctypes.sizeof(data))

        set_dwm_attribute(20, 1)
        set_dwm_attribute(19, 1)
        set_dwm_attribute(34, colorref("#1e3b2b"))
        set_dwm_attribute(35, colorref("#050807"))
        set_dwm_attribute(36, colorref("#dde7df"))
    except Exception:
        return


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("This program injects text with Windows SendInput and must run on Windows.")

    api = DesktopApi()
    window = webview.create_window(
        "Flow Voice",
        ui_url(),
        js_api=api,
        width=1240,
        height=860,
        min_size=(1120, 780),
        frameless=True,
        easy_drag=False,
        draggable=True,
        shadow=True,
        background_color="#050807",
    )
    api.window = window
    window.events.loaded += lambda: apply_window_chrome(window)
    window.events.closing += lambda: api.shutdown()
    webview.start(gui="edgechromium", debug=False)


if __name__ == "__main__":
    main()
