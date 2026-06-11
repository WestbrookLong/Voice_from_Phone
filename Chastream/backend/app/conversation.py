from __future__ import annotations

import json
import os
from pathlib import Path


def process_conversation(record: dict) -> dict:
    core_root = Path(os.environ["CHASTREAM_DATA_ROOT"])
    core_root.mkdir(parents=True, exist_ok=True)

    from .chastream_core.manager import ChastreamManager

    metadata = record["metadata"]
    manager = ChastreamManager()
    selected_speaker_ids = list(metadata.get("selectedSpeakerIds") or [])
    if not selected_speaker_ids:
        selected_speaker_ids = [
            collection.id
            for collection in manager.profiles.load_all()
            if any(
                not element.hidden and element.centroid
                for element in collection.elements
            )
        ]
    if not selected_speaker_ids:
        raise RuntimeError("服务器尚未注册可用的声纹集合。")
    manager.settings.voiceprint_threshold = float(
        metadata.get("voiceprintThreshold", manager.settings.voiceprint_threshold)
    )
    manager.settings.voiceprint_margin = float(
        metadata.get("voiceprintMargin", manager.settings.voiceprint_margin)
    )
    manager.settings.scl_trigger_threshold = float(
        metadata.get("sclTriggerThreshold", manager.settings.scl_trigger_threshold)
    )
    manager.settings.enable_scl = bool(
        metadata.get("enableScl", manager.settings.enable_scl)
    )
    state = manager.process_existing(
        Path(record["audio_path"]),
        record["title"] or "移动端对话",
        str(metadata.get("speakerMode", "two")),
        selected_speaker_ids,
        analysis_style=record["style"],
    )
    manager.worker.join()
    session = manager.active
    if not session or session.status != "done":
        raise RuntimeError(session.error if session else "Conversation processing failed.")
    session_dir = manager.sessions.directory(session.id)
    dialogue = _read_json(session_dir / "dialogue.json")
    analysis = _read_json(session_dir / "analysis.json")
    return {
        "title": str(analysis.get("title") or session.title),
        "summary": str(analysis.get("overview") or "")[:120],
        "content": (session_dir / "analysis.md").read_text(encoding="utf-8"),
        "raw_transcript": "\n".join(
            str(item.get("text", "")) for item in session.transcript_sentences
        ),
        "result_json": {
            "coreSessionId": session.id,
            "dialogue": dialogue,
            "analysis": analysis,
            "settings": metadata,
        },
    }


def _read_json(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
