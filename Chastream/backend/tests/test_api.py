from pathlib import Path

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


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
