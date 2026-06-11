from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    data_root: Path = Path(
        os.environ.get("CHASTREAM_MOBILE_DATA_ROOT", BACKEND_ROOT / "data")
    ).resolve()
    api_token: str = os.environ.get("CHASTREAM_API_TOKEN", "").strip()
    dashscope_api_key: str = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    public_base_path: str = os.environ.get(
        "CHASTREAM_PUBLIC_BASE_PATH", "/chastream"
    ).rstrip("/")
    max_upload_mb: int = int(os.environ.get("CHASTREAM_MAX_UPLOAD_MB", "500"))

    def prepare(self) -> None:
        for name in ("uploads", "quick-notes", "conversations", "core"):
            (self.data_root / name).mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.prepare()
os.environ.setdefault("CHASTREAM_DATA_ROOT", str(settings.data_root / "core"))
