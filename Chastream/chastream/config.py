from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = Path(os.environ.get("CHASTREAM_DATA_ROOT", APP_ROOT / "data")).resolve()
SESSIONS_ROOT = DATA_ROOT / "sessions"
PROFILES_ROOT = DATA_ROOT / "profiles"
MODELS_ROOT = DATA_ROOT / "models"
CACHE_ROOT = DATA_ROOT / "cache"
TEMP_ROOT = DATA_ROOT / "temp"
SETTINGS_PATH = DATA_ROOT / "settings.json"


def configure_local_caches() -> None:
    for path in (DATA_ROOT, SESSIONS_ROOT, PROFILES_ROOT, MODELS_ROOT, CACHE_ROOT, TEMP_ROOT):
        path.mkdir(parents=True, exist_ok=True)
    defaults = {
        "MODELSCOPE_CACHE": CACHE_ROOT / "modelscope",
        "MODELSCOPE_HOME": CACHE_ROOT / "modelscope",
        "HF_HOME": CACHE_ROOT / "huggingface",
        "HUGGINGFACE_HUB_CACHE": CACHE_ROOT / "huggingface" / "hub",
        "TORCH_HOME": CACHE_ROOT / "torch",
        "TMP": TEMP_ROOT,
        "TEMP": TEMP_ROOT,
    }
    for name, value in defaults.items():
        os.environ[name] = str(value)
        value.mkdir(parents=True, exist_ok=True)


@dataclass
class AppSettings:
    asr_model: str = "paraformer-v2"
    asr_vocabulary_id: str = ""
    asr_language_hints: str = "zh,en"
    speaker_mode: str = "two"
    qwen_model: str = "qwen-plus"
    voiceprint_threshold: float = 0.33
    voiceprint_margin: float = 0.06
    minimum_speech_ms: int = 1200
    enable_scl: bool = True
    scl_window_ms: int = 7000
    scl_stride_ms: int = 3500

    @classmethod
    def load(cls) -> "AppSettings":
        configure_local_caches()
        if not SETTINGS_PATH.exists():
            return cls()
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        allowed = cls.__dataclass_fields__.keys()
        settings = cls(**{key: value for key, value in data.items() if key in allowed})
        if settings.speaker_mode == "auto":
            settings.speaker_mode = "two"
        return settings

    def save(self) -> None:
        configure_local_caches()
        SETTINGS_PATH.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
