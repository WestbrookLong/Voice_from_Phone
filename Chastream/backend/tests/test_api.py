from pathlib import Path

from fastapi.testclient import TestClient

from app.db import database
from app.main import app
from app.quick_notes import _append, _fallback_title


def setup_function():
    database.reset()


def test_health():
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["service"] == "chastream-mobile"


def test_empty_audio_is_rejected():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/quick-notes",
            files={"audio": ("empty.wav", b"", "audio/wav")},
        )
    assert response.status_code == 400


def test_job_state_is_process_local():
    record, job = database.create_record(
        kind="quick_note",
        audio_path="/tmp/example.wav",
        style="formal_paragraph",
        source="test",
        metadata={},
    )
    assert database.get_record(record["id"])["status"] == "queued"
    assert database.get_job(job["id"])["status"] == "queued"
    assert not hasattr(database, "path")


def test_quick_note_append_keeps_existing_text_unchanged():
    assert _append("用户已经编辑的正文。", "本次新增内容。") == (
        "用户已经编辑的正文。\n\n本次新增内容。"
    )
    assert _fallback_title(" 这是 一段 新内容 ") == "这是一段新内容"
