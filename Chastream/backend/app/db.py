from __future__ import annotations

import copy
import json
import threading
import uuid
from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    """Process-local job state.

    Mobile devices own the durable note history. The server keeps only enough
    state for upload polling and loses it intentionally when the service
    restarts.
    """

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.records: dict[str, dict] = {}
        self.jobs: dict[str, dict] = {}

    def create_record(
        self,
        *,
        kind: str,
        audio_path: str,
        style: str,
        source: str,
        metadata: dict,
        title: str = "",
    ) -> tuple[dict, dict]:
        record_id = uuid.uuid4().hex
        job_id = uuid.uuid4().hex
        stamp = now_iso()
        record = {
            "id": record_id,
            "kind": kind,
            "title": title,
            "summary": "",
            "content": "",
            "raw_transcript": "",
            "status": "queued",
            "style": style,
            "audio_path": audio_path,
            "source": source,
            "metadata": copy.deepcopy(metadata),
            "result": {},
            "error": None,
            "created_at": stamp,
            "updated_at": stamp,
        }
        job = {
            "id": job_id,
            "record_id": record_id,
            "job_type": kind,
            "status": "queued",
            "attempts": 0,
            "error": None,
            "created_at": stamp,
            "updated_at": stamp,
        }
        with self.lock:
            self.records[record_id] = record
            self.jobs[job_id] = job
        return self.get_record(record_id), self.get_job(job_id)

    def get_record(self, record_id: str) -> dict:
        with self.lock:
            try:
                return copy.deepcopy(self.records[record_id])
            except KeyError:
                raise KeyError(record_id) from None

    def list_records(self, kind: str, limit: int = 20) -> list[dict]:
        with self.lock:
            records = [
                copy.deepcopy(record)
                for record in self.records.values()
                if record["kind"] == kind
            ]
        records.sort(key=lambda item: item["created_at"], reverse=True)
        return records[: max(1, min(limit, 100))]

    def get_job(self, job_id: str) -> dict:
        with self.lock:
            try:
                return copy.deepcopy(self.jobs[job_id])
            except KeyError:
                raise KeyError(job_id) from None

    def claim_job(self) -> dict | None:
        with self.lock:
            queued = sorted(
                (job for job in self.jobs.values() if job["status"] == "queued"),
                key=lambda item: item["created_at"],
            )
            if not queued:
                return None
            job = queued[0]
            stamp = now_iso()
            job["status"] = "processing"
            job["attempts"] += 1
            job["updated_at"] = stamp
            record = self.records[job["record_id"]]
            record["status"] = "processing"
            record["updated_at"] = stamp
            return copy.deepcopy(job)

    def complete(self, job_id: str, record_id: str, values: dict) -> None:
        stamp = now_iso()
        allowed = {"title", "summary", "content", "raw_transcript", "result_json"}
        with self.lock:
            record = self.records[record_id]
            record["status"] = "done"
            record["error"] = None
            record["updated_at"] = stamp
            for key, value in values.items():
                if key not in allowed:
                    continue
                if key == "result_json":
                    record["result"] = copy.deepcopy(value)
                else:
                    record[key] = str(value)
            job = self.jobs[job_id]
            job["status"] = "done"
            job["error"] = None
            job["updated_at"] = stamp

    def fail(self, job_id: str, record_id: str, error: str) -> None:
        stamp = now_iso()
        with self.lock:
            record = self.records[record_id]
            record["status"] = "failed"
            record["error"] = error
            record["updated_at"] = stamp
            job = self.jobs[job_id]
            job["status"] = "failed"
            job["error"] = error
            job["updated_at"] = stamp

    def retry(self, record_id: str) -> dict:
        record = self.get_record(record_id)
        if record["status"] not in {"failed", "done"}:
            raise ValueError("Only failed or completed records can be retried.")
        if not record["audio_path"]:
            raise ValueError("The temporary audio has already been deleted; upload it again.")
        job_id = uuid.uuid4().hex
        stamp = now_iso()
        job = {
            "id": job_id,
            "record_id": record_id,
            "job_type": record["kind"],
            "status": "queued",
            "attempts": 0,
            "error": None,
            "created_at": stamp,
            "updated_at": stamp,
        }
        with self.lock:
            stored = self.records[record_id]
            stored["status"] = "queued"
            stored["error"] = None
            stored["updated_at"] = stamp
            self.jobs[job_id] = job
        return copy.deepcopy(job)

    def clear_audio_path(self, record_id: str) -> None:
        with self.lock:
            if record_id in self.records:
                self.records[record_id]["audio_path"] = ""

    def reset(self) -> None:
        with self.lock:
            self.records.clear()
            self.jobs.clear()


database = Database()
