from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .config import settings


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or settings.data_root / "chastream-mobile.sqlite3"
        self.lock = threading.RLock()
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS records (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL DEFAULT '',
                    raw_transcript TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    style TEXT NOT NULL DEFAULT 'meeting_notes',
                    audio_path TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'app',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    record_id TEXT NOT NULL,
                    job_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(record_id) REFERENCES records(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_records_kind_created
                    ON records(kind, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_jobs_status_created
                    ON jobs(status, created_at);
                """
            )

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
        with self.lock, self.connect() as connection:
            connection.execute(
                """
                INSERT INTO records (
                    id, kind, title, status, style, audio_path, source,
                    metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?)
                """,
                (
                    record_id,
                    kind,
                    title,
                    style,
                    audio_path,
                    source,
                    json.dumps(metadata, ensure_ascii=False),
                    stamp,
                    stamp,
                ),
            )
            connection.execute(
                """
                INSERT INTO jobs (
                    id, record_id, job_type, status, created_at, updated_at
                ) VALUES (?, ?, ?, 'queued', ?, ?)
                """,
                (job_id, record_id, kind, stamp, stamp),
            )
        return self.get_record(record_id), self.get_job(job_id)

    def get_record(self, record_id: str) -> dict:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM records WHERE id = ?", (record_id,)
            ).fetchone()
        if row is None:
            raise KeyError(record_id)
        return self._record(row)

    def list_records(self, kind: str, limit: int = 20) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM records
                WHERE kind = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (kind, max(1, min(limit, 100))),
            ).fetchall()
        return [self._record(row) for row in rows]

    def get_job(self, job_id: str) -> dict:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        if row is None:
            raise KeyError(job_id)
        return dict(row)

    def claim_job(self) -> dict | None:
        with self.lock, self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM jobs
                WHERE status = 'queued'
                ORDER BY created_at
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            stamp = now_iso()
            updated = connection.execute(
                """
                UPDATE jobs
                SET status = 'processing', attempts = attempts + 1, updated_at = ?
                WHERE id = ? AND status = 'queued'
                """,
                (stamp, row["id"]),
            )
            if updated.rowcount != 1:
                connection.rollback()
                return None
            connection.execute(
                "UPDATE records SET status = 'processing', updated_at = ? WHERE id = ?",
                (stamp, row["record_id"]),
            )
            connection.commit()
            return self.get_job(row["id"])

    def complete(self, job_id: str, record_id: str, values: dict) -> None:
        stamp = now_iso()
        allowed = {
            "title",
            "summary",
            "content",
            "raw_transcript",
            "result_json",
        }
        assignments = ["status = 'done'", "error = NULL", "updated_at = ?"]
        params: list[object] = [stamp]
        for key, value in values.items():
            if key not in allowed:
                continue
            assignments.append(f"{key} = ?")
            params.append(
                json.dumps(value, ensure_ascii=False)
                if key == "result_json"
                else str(value)
            )
        params.append(record_id)
        with self.lock, self.connect() as connection:
            connection.execute(
                f"UPDATE records SET {', '.join(assignments)} WHERE id = ?",
                params,
            )
            connection.execute(
                """
                UPDATE jobs SET status = 'done', error = NULL, updated_at = ?
                WHERE id = ?
                """,
                (stamp, job_id),
            )

    def fail(self, job_id: str, record_id: str, error: str) -> None:
        stamp = now_iso()
        with self.lock, self.connect() as connection:
            connection.execute(
                """
                UPDATE records SET status = 'failed', error = ?, updated_at = ?
                WHERE id = ?
                """,
                (error, stamp, record_id),
            )
            connection.execute(
                """
                UPDATE jobs SET status = 'failed', error = ?, updated_at = ?
                WHERE id = ?
                """,
                (error, stamp, job_id),
            )

    def retry(self, record_id: str) -> dict:
        record = self.get_record(record_id)
        if record["status"] not in {"failed", "done"}:
            raise ValueError("Only failed or completed records can be retried.")
        job_id = uuid.uuid4().hex
        stamp = now_iso()
        with self.lock, self.connect() as connection:
            connection.execute(
                "UPDATE records SET status = 'queued', error = NULL, updated_at = ? WHERE id = ?",
                (stamp, record_id),
            )
            connection.execute(
                """
                INSERT INTO jobs (
                    id, record_id, job_type, status, created_at, updated_at
                ) VALUES (?, ?, ?, 'queued', ?, ?)
                """,
                (job_id, record_id, record["kind"], stamp, stamp),
            )
        return self.get_job(job_id)

    @staticmethod
    def _record(row: sqlite3.Row) -> dict:
        value = dict(row)
        value["metadata"] = json.loads(value.pop("metadata_json") or "{}")
        value["result"] = json.loads(value.pop("result_json") or "{}")
        return value


database = Database()
