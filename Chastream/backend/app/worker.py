from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from .config import settings
from .conversation import process_conversation
from .db import database
from .quick_notes import process_quick_note


class JobWorker:
    def __init__(self) -> None:
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        os.environ.setdefault(
            "CHASTREAM_DATA_ROOT", str(settings.data_root / "core")
        )
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=10)

    def run(self) -> None:
        while not self.stop_event.is_set():
            job = database.claim_job()
            if not job:
                self.stop_event.wait(1.5)
                continue
            record = database.get_record(job["record_id"])
            try:
                if job["job_type"] == "quick_note":
                    result = process_quick_note(
                        Path(record["audio_path"]), record["style"]
                    )
                    values = {
                        "title": result["title"],
                        "summary": result["summary"],
                        "content": result["content"],
                        "raw_transcript": result["rawTranscript"],
                        "result_json": result,
                    }
                elif job["job_type"] == "conversation":
                    values = process_conversation(record)
                else:
                    raise RuntimeError(f"Unsupported job type: {job['job_type']}")
                database.complete(job["id"], record["id"], values)
            except Exception as exc:
                database.fail(job["id"], record["id"], str(exc))
            time.sleep(0.2)


worker = JobWorker()
