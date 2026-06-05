from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from ...prompts import build_polish_messages
from .base import PolishProvider


class BailianQwenPolishProvider(PolishProvider):
    name = "bailian_qwen"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float = 60,
    ) -> None:
        self.api_key = api_key or os.environ.get("DASHSCOPE_API_KEY", "")
        self.model = model or os.environ.get("FLOWVOICE_POLISH_MODEL", "qwen-plus")
        self.base_url = (base_url or os.environ.get("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")).rstrip("/")
        self.timeout = timeout

    def available(self) -> bool:
        return bool(self.api_key)

    def polish(self, transcript: str, style: str, glossary: str = "", incremental: bool = False) -> str:
        if not self.api_key:
            raise RuntimeError("DASHSCOPE_API_KEY is not configured.")
        text = (transcript or "").strip()
        if not text:
            return ""

        payload = {
            "model": self.model,
            "messages": build_polish_messages(text, style, glossary=glossary, incremental=incremental),
            "temperature": 0.2,
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=data,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Bailian Qwen request failed: HTTP {exc.code} {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Bailian Qwen request failed: {exc.reason}") from exc

        result = json.loads(body)
        choices = result.get("choices") if isinstance(result, dict) else None
        if not choices:
            raise RuntimeError(f"Bailian Qwen returned no choices: {body}")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, list):
            parts = [part.get("text", "") for part in content if isinstance(part, dict)]
            content = "".join(parts)
        return str(content or "").strip()
