from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests

from .models import TimedWord, TranscriptSentence


ASR_ENDPOINT = "https://dashscope.aliyuncs.com/api/v1/services/audio/asr/transcription"
TASK_ENDPOINT = "https://dashscope.aliyuncs.com/api/v1/tasks"
UPLOAD_POLICY_ENDPOINT = "https://dashscope.aliyuncs.com/api/v1/uploads"


class DashScopeTemporaryUploader:
    """Uploads one file to DashScope's 48-hour temporary OSS storage."""

    def __init__(self, api_key: str | None = None, model: str = "paraformer-v2") -> None:
        self.api_key = (api_key or os.environ.get("DASHSCOPE_API_KEY", "")).strip()
        self.model = model

    def upload(self, path: Path) -> str:
        if not self.api_key:
            raise RuntimeError("DASHSCOPE_API_KEY is not configured.")
        response = requests.get(
            UPLOAD_POLICY_ENDPOINT,
            params={"action": "getPolicy", "model": self.model},
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            timeout=30,
        )
        self._raise(response, "get upload policy")
        policy = response.json().get("data") or {}
        key = f"{policy['upload_dir']}/{path.name}"
        fields = {
            "OSSAccessKeyId": (None, policy["oss_access_key_id"]),
            "Signature": (None, policy["signature"]),
            "policy": (None, policy["policy"]),
            "x-oss-object-acl": (None, policy["x_oss_object_acl"]),
            "x-oss-forbid-overwrite": (None, policy["x_oss_forbid_overwrite"]),
            "key": (None, key),
            "success_action_status": (None, "200"),
        }
        with path.open("rb") as handle:
            fields["file"] = (path.name, handle, "audio/wav")
            upload = requests.post(policy["upload_host"], files=fields, timeout=180)
        self._raise(upload, "upload audio")
        return f"oss://{key}"

    @staticmethod
    def _raise(response: requests.Response, action: str) -> None:
        if response.status_code >= 400:
            raise RuntimeError(f"DashScope failed to {action}: HTTP {response.status_code} {response.text}")


class ParaformerTimestampProvider:
    def __init__(
        self,
        api_key: str | None = None,
        model: str = "paraformer-v2",
        vocabulary_id: str = "",
        language_hints: list[str] | None = None,
    ) -> None:
        self.api_key = (api_key or os.environ.get("DASHSCOPE_API_KEY", "")).strip()
        self.model = model.strip() or "paraformer-v2"
        self.vocabulary_id = vocabulary_id.strip()
        self.language_hints = language_hints or ["zh", "en"]

    def submit(self, file_url: str) -> str:
        if not self.api_key:
            raise RuntimeError("DASHSCOPE_API_KEY is not configured.")
        parameters = {
            "channel_id": [0],
            "language_hints": self.language_hints,
            "timestamp_alignment_enabled": True,
            "diarization_enabled": False,
        }
        if self.vocabulary_id:
            parameters["vocabulary_id"] = self.vocabulary_id
        payload = {
            "model": self.model,
            "input": {"file_urls": [file_url]},
            "parameters": parameters,
        }
        headers = self._headers(resolve_oss=file_url.startswith("oss://"))
        headers["X-DashScope-Async"] = "enable"
        response = requests.post(ASR_ENDPOINT, headers=headers, json=payload, timeout=60)
        result = self._result(response, "submit transcription")
        task_id = str((result.get("output") or {}).get("task_id", "")).strip()
        if not task_id:
            raise RuntimeError(f"Paraformer did not return task_id: {json.dumps(result, ensure_ascii=False)}")
        return task_id

    def wait(self, task_id: str, timeout_seconds: int = 3600, poll_seconds: float = 3.0) -> dict:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            response = requests.post(
                f"{TASK_ENDPOINT}/{task_id}",
                headers=self._headers(resolve_oss=False),
                timeout=60,
            )
            result = self._result(response, "query transcription")
            output = result.get("output") or {}
            status = str(output.get("task_status", "")).upper()
            if status == "SUCCEEDED":
                transcription_url = self._find_transcription_url(output)
                if not transcription_url:
                    raise RuntimeError("Paraformer completed without a transcription URL.")
                output["transcription_url"] = transcription_url
                return output
            if status in {"FAILED", "CANCELED", "UNKNOWN"}:
                message = output.get("message") or output.get("code") or status
                raise RuntimeError(f"Paraformer task failed: {message}")
            time.sleep(poll_seconds)
        raise TimeoutError("Timed out waiting for Paraformer transcription.")

    def fetch_transcription(
        self,
        url: str,
    ) -> tuple[dict, list[TranscriptSentence], list[TimedWord]]:
        response = requests.get(url, timeout=60)
        if response.status_code >= 400:
            raise RuntimeError(f"Unable to download Paraformer transcription: HTTP {response.status_code}")
        raw = response.json()
        sentences: list[TranscriptSentence] = []
        all_words: list[TimedWord] = []
        sentence_index = 0
        for transcript in raw.get("transcripts") or []:
            for sentence in transcript.get("sentences") or []:
                sentence_index += 1
                sentence_id = str(sentence.get("sentence_id", sentence_index))
                timed_words = []
                for word_index, word in enumerate(sentence.get("words") or [], start=1):
                    timed_word = TimedWord(
                        id=f"word-{sentence_index}-{word_index}",
                        start_ms=int(word.get("begin_time", sentence.get("begin_time", 0))),
                        end_ms=int(word.get("end_time", sentence.get("end_time", 0))),
                        text=str(word.get("text", "")),
                        punctuation=str(word.get("punctuation") or ""),
                        sentence_id=sentence_id,
                    )
                    timed_words.append(timed_word)
                    all_words.append(timed_word)
                if not timed_words and str(sentence.get("text", "")).strip():
                    fallback = TimedWord(
                        id=f"word-{sentence_index}-1",
                        start_ms=int(sentence.get("begin_time", 0)),
                        end_ms=int(sentence.get("end_time", 0)),
                        text=str(sentence.get("text", "")).strip(),
                        sentence_id=sentence_id,
                    )
                    timed_words.append(fallback)
                    all_words.append(fallback)
                sentences.append(
                    TranscriptSentence(
                        id=f"sentence-{sentence_index}",
                        start_ms=int(sentence.get("begin_time", timed_words[0].start_ms if timed_words else 0)),
                        end_ms=int(sentence.get("end_time", timed_words[-1].end_ms if timed_words else 0)),
                        text=str(sentence.get("text", "")).strip() or _join_words(timed_words),
                        words=timed_words,
                    )
                )
        return raw, sentences, all_words

    def _headers(self, *, resolve_oss: bool) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if resolve_oss:
            headers["X-DashScope-OssResourceResolve"] = "enable"
        return headers

    @staticmethod
    def _result(response: requests.Response, action: str) -> dict:
        if response.status_code >= 400:
            raise RuntimeError(f"DashScope failed to {action}: HTTP {response.status_code} {response.text}")
        result = response.json()
        if result.get("code"):
            raise RuntimeError(f"DashScope {result.get('code')}: {result.get('message', '')}")
        return result

    @staticmethod
    def _find_transcription_url(output: dict) -> str:
        for item in output.get("results") or []:
            url = str(item.get("transcription_url", "")).strip()
            if url:
                return url
        return str(output.get("transcription_url", "")).strip()


def _join_words(words: list[TimedWord]) -> str:
    value = ""
    for word in words:
        token = f"{word.text}{word.punctuation}"
        if value and _needs_space(value[-1], token[:1]):
            value += " "
        value += token
    return value.strip()


def _needs_space(left: str, right: str) -> bool:
    return bool(left and right and left.isascii() and right.isascii() and left.isalnum() and right.isalnum())
