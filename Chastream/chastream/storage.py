from __future__ import annotations

import json
import re
import secrets
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .config import PROFILES_ROOT, SESSIONS_ROOT, configure_local_caches
from .models import SessionState, VoiceProfile


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "-", value.strip()).strip("-")
    return cleaned[:40] or "session"


class SessionRepository:
    def __init__(self) -> None:
        configure_local_caches()

    def create(self, title: str, speaker_mode: str) -> SessionState:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        session_id = f"{stamp}-{secrets.token_hex(3)}"
        session = SessionState(id=session_id, title=title or stamp, speaker_mode=speaker_mode)
        self.directory(session_id).mkdir(parents=True, exist_ok=True)
        session.audio_path = str(self.directory(session_id) / "audio.wav")
        self.save(session)
        return session

    def directory(self, session_id: str) -> Path:
        return SESSIONS_ROOT / _safe_name(session_id)

    def save(self, session: SessionState) -> None:
        session.touch()
        directory = self.directory(session.id)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "session.json").write_text(
            json.dumps(session.snapshot(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def write_json(self, session_id: str, name: str, value) -> Path:
        path = self.directory(session_id) / name
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def write_text(self, session_id: str, name: str, value: str) -> Path:
        path = self.directory(session_id) / name
        path.write_text(value, encoding="utf-8")
        return path

    def list_recent(self, limit: int = 20) -> list[dict]:
        results = []
        for path in sorted(SESSIONS_ROOT.glob("*/session.json"), reverse=True):
            try:
                results.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
            if len(results) >= limit:
                break
        return results


class ProfileRepository:
    def __init__(self) -> None:
        configure_local_caches()

    def save(self, profile: VoiceProfile) -> None:
        profile.updated_at = datetime.now().astimezone().isoformat()
        path = PROFILES_ROOT / f"{_safe_name(profile.id)}.json"
        path.write_text(json.dumps(asdict(profile), ensure_ascii=False, indent=2), encoding="utf-8")

    def load_all(self) -> list[VoiceProfile]:
        profiles = []
        for path in PROFILES_ROOT.glob("*.json"):
            try:
                profiles.append(VoiceProfile(**json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, json.JSONDecodeError, TypeError):
                continue
        return profiles

    def delete(self, profile_id: str) -> None:
        path = PROFILES_ROOT / f"{_safe_name(profile_id)}.json"
        if path.exists():
            path.unlink()

