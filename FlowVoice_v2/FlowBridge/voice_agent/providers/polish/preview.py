from __future__ import annotations

import re

from .base import PolishProvider


FILLER_PATTERN = re.compile(
    r"(嗯+|呃+|啊+|这个|那个|就是说|然后然后|对吧|是不是|其实就是|然后\s*)"
)
SPACE_PATTERN = re.compile(r"\s+")


class PreviewPolishProvider(PolishProvider):
    name = "preview"

    def polish(self, transcript: str, style: str, glossary: str = "", incremental: bool = False) -> str:
        text = SPACE_PATTERN.sub(" ", transcript or "").strip()
        text = FILLER_PATTERN.sub("", text).strip()
        if not text:
            return ""
        if style == "summary_bullets":
            chunks = [chunk.strip(" ，。；;") for chunk in re.split(r"[。；;\n]", text) if chunk.strip()]
            return "\n".join(f"- {chunk}" for chunk in chunks[:8]) or text
        if style == "todo_items":
            return text if any(word in text for word in ("需要", "安排", "负责", "完成", "处理")) else "未识别到明确待办事项。"
        return text
