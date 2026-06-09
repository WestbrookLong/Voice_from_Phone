from __future__ import annotations

import json
import re
import secrets
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .config import PROFILES_ROOT, SESSIONS_ROOT, configure_local_caches
from .models import SessionState, SpeakerCollection, VoiceElement


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "-", value.strip()).strip("-")
    return cleaned[:40] or "session"


class SessionRepository:
    def __init__(self) -> None:
        configure_local_caches()

    def create(
        self,
        title: str,
        speaker_mode: str,
        selected_speaker_ids: list[str] | None = None,
        analysis_style: str = "chat",
        selected_voiceprint_elements: dict[str, list[str]] | None = None,
    ) -> SessionState:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        session_id = f"{stamp}-{secrets.token_hex(3)}"
        session = SessionState(
            id=session_id,
            title=title or stamp,
            speaker_mode=speaker_mode,
            selected_speaker_ids=list(selected_speaker_ids or []),
            selected_voiceprint_elements={
                str(collection_id): list(element_ids)
                for collection_id, element_ids in (selected_voiceprint_elements or {}).items()
            },
            analysis_style=analysis_style,
        )
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

    def load(self, session_id: str) -> SessionState:
        directory = self.directory(session_id)
        path = directory / "session.json"
        if not path.exists():
            raise FileNotFoundError(f"历史会话不存在：{session_id}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"历史会话数据损坏：{session_id}") from exc
        allowed = SessionState.__dataclass_fields__.keys()
        session = SessionState(**{key: value for key, value in data.items() if key in allowed})
        if session.id != session_id:
            raise RuntimeError("历史会话 ID 与目录不一致。")
        if not session.resolved_utterances:
            session.resolved_utterances = self._read_json(directory / "dialogue.json", [])
        self._restore_match_details(
            session.resolved_utterances,
            self._read_json(directory / "voiceprint.diagnostics.json", []),
        )
        if not session.analysis:
            session.analysis = self._read_json(directory / "analysis.json", {})
        return session

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

    @staticmethod
    def _read_json(path: Path, fallback):
        if not path.exists():
            return fallback
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return fallback

    @staticmethod
    def _restore_match_details(utterances: list[dict], diagnostics: list[dict]) -> None:
        matches = {
            item.get("segmentId"): item.get("match")
            for item in diagnostics
            if isinstance(item, dict) and item.get("segmentId") and isinstance(item.get("match"), dict)
        }
        for utterance in utterances:
            match = matches.get(utterance.get("id"))
            if not match:
                continue
            utterance.setdefault("second_score", float(match.get("second_score", 0.0)))
            utterance.setdefault("margin", float(match.get("margin", 0.0)))


class ProfileRepository:
    def __init__(self) -> None:
        configure_local_caches()

    def save(self, collection: SpeakerCollection) -> None:
        collection.schema_version = 2
        collection.updated_at = datetime.now().astimezone().isoformat()
        path = PROFILES_ROOT / f"{_safe_name(collection.id)}.json"
        path.write_text(json.dumps(asdict(collection), ensure_ascii=False, indent=2), encoding="utf-8")

    def load_all(self) -> list[SpeakerCollection]:
        collections = []
        for path in PROFILES_ROOT.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                collection, migrated = self._decode_collection(data)
                collections.append(collection)
                if migrated:
                    self.save(collection)
            except (OSError, json.JSONDecodeError, TypeError):
                continue
        return collections

    def get(self, collection_id: str) -> SpeakerCollection:
        for collection in self.load_all():
            if collection.id == collection_id:
                return collection
        raise KeyError(f"声纹集合不存在：{collection_id}")

    def delete(self, collection_id: str) -> None:
        path = PROFILES_ROOT / f"{_safe_name(collection_id)}.json"
        if path.exists():
            path.unlink()

    @staticmethod
    def _decode_collection(data: dict) -> tuple[SpeakerCollection, bool]:
        if int(data.get("schema_version", 0) or 0) >= 2 or "elements" in data:
            elements = [
                VoiceElement(**item)
                for item in data.get("elements", [])
                if isinstance(item, dict)
            ]
            allowed = SpeakerCollection.__dataclass_fields__.keys()
            values = {key: value for key, value in data.items() if key in allowed and key != "elements"}
            return SpeakerCollection(**values, elements=elements), False

        element = VoiceElement(
            id=f"element-{data['id']}",
            name="默认声音",
            model_id=str(data.get("model_id", "")),
            sample_paths=list(data.get("sample_paths") or []),
            embeddings=list(data.get("embeddings") or []),
            centroid=list(data.get("centroid") or []),
            created_at=str(data.get("created_at") or datetime.now().astimezone().isoformat()),
            updated_at=str(data.get("updated_at") or datetime.now().astimezone().isoformat()),
        )
        collection = SpeakerCollection(
            id=str(data["id"]),
            name=str(data.get("name") or "未命名发言人"),
            elements=[element],
            created_at=str(data.get("created_at") or datetime.now().astimezone().isoformat()),
            updated_at=str(data.get("updated_at") or datetime.now().astimezone().isoformat()),
        )
        return collection, True
