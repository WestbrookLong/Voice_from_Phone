from __future__ import annotations

import json
import shutil
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from .auth import require_api_token
from .config import settings
from .db import database
from .worker import worker


@asynccontextmanager
async def lifespan(_: FastAPI):
    worker.start()
    yield
    worker.stop()


app = FastAPI(
    title="Chastream Mobile API",
    version="0.1.0",
    root_path=settings.public_base_path,
    lifespan=lifespan,
)


class NamePayload(BaseModel):
    name: str


class ElementPayload(BaseModel):
    name: str | None = None
    hidden: bool | None = None


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "service": "chastream-mobile",
        "version": app.version,
    }


@app.post("/api/v1/quick-notes", dependencies=[Depends(require_api_token)])
def create_quick_note(
    audio: UploadFile = File(...),
    style: str = Form("formal_paragraph"),
    source: str = Form("app"),
) -> dict:
    path = _save_upload(audio, "quick-notes")
    record, job = database.create_record(
        kind="quick_note",
        audio_path=str(path),
        style=style,
        source=source,
        metadata={},
    )
    return {"record": record, "job": job}


@app.get("/api/v1/quick-notes", dependencies=[Depends(require_api_token)])
def list_quick_notes(limit: int = 20) -> dict:
    return {"items": database.list_records("quick_note", limit)}


@app.get("/api/v1/quick-notes/{record_id}", dependencies=[Depends(require_api_token)])
def get_quick_note(record_id: str) -> dict:
    return _get_record(record_id, "quick_note")


@app.post("/api/v1/conversations", dependencies=[Depends(require_api_token)])
def create_conversation(
    audio: UploadFile = File(...),
    title: str = Form(""),
    style: str = Form("chat"),
    source: str = Form("app"),
    metadata_json: str = Form("{}"),
) -> dict:
    try:
        metadata = json.loads(metadata_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="metadata_json is invalid.") from exc
    path = _save_upload(audio, "conversations")
    record, job = database.create_record(
        kind="conversation",
        audio_path=str(path),
        style=style,
        source=source,
        metadata=metadata,
        title=title,
    )
    return {"record": record, "job": job}


@app.get("/api/v1/conversations", dependencies=[Depends(require_api_token)])
def list_conversations(limit: int = 20) -> dict:
    return {"items": database.list_records("conversation", limit)}


@app.get("/api/v1/conversations/{record_id}", dependencies=[Depends(require_api_token)])
def get_conversation(record_id: str) -> dict:
    return _get_record(record_id, "conversation")


@app.get("/api/v1/jobs/{job_id}", dependencies=[Depends(require_api_token)])
def get_job(job_id: str) -> dict:
    try:
        return database.get_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Job not found.") from exc


@app.post("/api/v1/records/{record_id}/retry", dependencies=[Depends(require_api_token)])
def retry_record(record_id: str) -> dict:
    try:
        return database.retry(record_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Record not found.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/v1/voiceprints", dependencies=[Depends(require_api_token)])
def list_voiceprints() -> dict:
    repository = _profile_repository()
    return {"items": [asdict(item) for item in repository.load_all()]}


@app.post("/api/v1/voiceprints/collections", dependencies=[Depends(require_api_token)])
def create_voiceprint_collection(payload: NamePayload) -> dict:
    from .chastream_core.models import SpeakerCollection

    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Collection name is required.")
    repository = _profile_repository()
    if any(item.name.casefold() == name.casefold() for item in repository.load_all()):
        raise HTTPException(status_code=409, detail="Collection name already exists.")
    collection = SpeakerCollection(id=f"person-{uuid.uuid4().hex[:10]}", name=name)
    repository.save(collection)
    return asdict(collection)


@app.patch(
    "/api/v1/voiceprints/collections/{collection_id}",
    dependencies=[Depends(require_api_token)],
)
def rename_voiceprint_collection(collection_id: str, payload: NamePayload) -> dict:
    repository = _profile_repository()
    collection = _get_collection(repository, collection_id)
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Collection name is required.")
    collection.name = name
    repository.save(collection)
    return asdict(collection)


@app.delete(
    "/api/v1/voiceprints/collections/{collection_id}",
    dependencies=[Depends(require_api_token)],
)
def delete_voiceprint_collection(collection_id: str) -> dict:
    repository = _profile_repository()
    collection = _get_collection(repository, collection_id)
    for element in collection.elements:
        for sample_path in element.sample_paths:
            Path(sample_path).unlink(missing_ok=True)
    repository.delete(collection_id)
    return {"ok": True}


@app.post(
    "/api/v1/voiceprints/collections/{collection_id}/elements",
    dependencies=[Depends(require_api_token)],
)
def create_voiceprint_element(
    collection_id: str,
    name: str = Form(...),
    samples: list[UploadFile] = File(...),
) -> dict:
    repository = _profile_repository()
    collection = _get_collection(repository, collection_id)
    clean_name = name.strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="Element name is required.")
    if any(item.name.casefold() == clean_name.casefold() for item in collection.elements):
        raise HTTPException(status_code=409, detail="Element name already exists.")
    import_dir = settings.data_root / "voiceprint-imports" / uuid.uuid4().hex
    import_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for sample in samples:
        path = import_dir / (Path(sample.filename or "sample.wav").name)
        with path.open("wb") as output:
            shutil.copyfileobj(sample.file, output)
        paths.append(path)
    try:
        from .chastream_core.manager import ChastreamManager

        manager = ChastreamManager()
        result = manager.enroll_element(collection_id, clean_name, paths)
        return result
    except ModuleNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail="Voiceprint worker dependencies are not installed.",
        ) from exc
    finally:
        for path in paths:
            path.unlink(missing_ok=True)
        import_dir.rmdir()


@app.patch(
    "/api/v1/voiceprints/collections/{collection_id}/elements/{element_id}",
    dependencies=[Depends(require_api_token)],
)
def update_voiceprint_element(
    collection_id: str,
    element_id: str,
    payload: ElementPayload,
) -> dict:
    repository = _profile_repository()
    collection = _get_collection(repository, collection_id)
    element = next((item for item in collection.elements if item.id == element_id), None)
    if element is None:
        raise HTTPException(status_code=404, detail="Element not found.")
    if payload.name is not None:
        element.name = payload.name.strip() or element.name
    if payload.hidden is not None:
        element.hidden = payload.hidden
    element.updated_at = datetime.now(timezone.utc).isoformat()
    repository.save(collection)
    return asdict(element)


@app.delete(
    "/api/v1/voiceprints/collections/{collection_id}/elements/{element_id}",
    dependencies=[Depends(require_api_token)],
)
def delete_voiceprint_element(collection_id: str, element_id: str) -> dict:
    repository = _profile_repository()
    collection = _get_collection(repository, collection_id)
    element = next((item for item in collection.elements if item.id == element_id), None)
    if element is None:
        raise HTTPException(status_code=404, detail="Element not found.")
    for sample_path in element.sample_paths:
        Path(sample_path).unlink(missing_ok=True)
    collection.elements = [item for item in collection.elements if item.id != element_id]
    repository.save(collection)
    return {"ok": True}


def _get_record(record_id: str, expected_kind: str) -> dict:
    try:
        record = database.get_record(record_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Record not found.") from exc
    if record["kind"] != expected_kind:
        raise HTTPException(status_code=404, detail="Record not found.")
    return record


def _save_upload(upload: UploadFile, category: str) -> Path:
    suffix = Path(upload.filename or "audio.wav").suffix.lower() or ".wav"
    if suffix not in {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"}:
        raise HTTPException(status_code=415, detail="Unsupported audio format.")
    path = settings.data_root / category / f"{uuid.uuid4().hex}{suffix}"
    total = 0
    with path.open("wb") as output:
        while chunk := upload.file.read(1024 * 1024):
            total += len(chunk)
            if total > settings.max_upload_mb * 1024 * 1024:
                output.close()
                path.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="Audio file is too large.")
            output.write(chunk)
    if total == 0:
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Audio file is empty.")
    return path


def _profile_repository():
    from .chastream_core.storage import ProfileRepository

    return ProfileRepository()


def _get_collection(repository, collection_id: str):
    try:
        return repository.get(collection_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Collection not found.") from exc
