from __future__ import annotations

import json
import os

import requests

from .analysis_prompts import build_analysis_messages, normalize_analysis_style
from .models import ResolvedUtterance


QWEN_ENDPOINT = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"


class QwenConversationAnalyst:
    def __init__(self, model: str = "qwen-plus", api_key: str | None = None) -> None:
        self.model = model
        self.api_key = (api_key or os.environ.get("DASHSCOPE_API_KEY", "")).strip()

    def analyze(self, utterances: list[ResolvedUtterance], style: str = "chat") -> dict:
        if not self.api_key:
            raise RuntimeError("DASHSCOPE_API_KEY is not configured.")
        transcript = "\n".join(self._transcript_line(item) for item in utterances)
        response = requests.post(
            QWEN_ENDPOINT,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={
                "model": self.model,
                "messages": build_analysis_messages(transcript, style),
                "temperature": 0.2,
            },
            timeout=120,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Qwen HTTP {response.status_code}: {response.text}")
        body = response.json()
        choices = body.get("choices") or []
        if not choices:
            raise RuntimeError("Qwen returned no choices.")
        content = str((choices[0].get("message") or {}).get("content", "")).strip()
        if content.startswith("```"):
            lines = content.splitlines()[1:]
            if lines and lines[-1].strip() == "```":
                lines.pop()
            content = "\n".join(lines).strip()
        try:
            result = json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Qwen returned invalid JSON: {content}") from exc
        if not isinstance(result, dict):
            raise RuntimeError("Qwen analysis must be a JSON object.")
        return result

    @staticmethod
    def to_markdown(result: dict, style: str = "chat") -> str:
        normalized = normalize_analysis_style(style)
        lines = [f"# {result.get('title') or '对话整理'}"]
        if normalized == "formal_paragraph":
            for paragraph in result.get("paragraphs") or []:
                if str(paragraph).strip():
                    lines.extend(["", str(paragraph).strip()])
            return "\n".join(lines).strip()
        if normalized == "summary_bullets":
            QwenConversationAnalyst._section_list(lines, "摘要要点", result.get("bullets"))
            return "\n".join(lines).strip()
        if normalized == "todo_items":
            QwenConversationAnalyst._append_actions(lines, result.get("actionItems"))
            return "\n".join(lines).strip()
        if normalized == "faithful_cleanup":
            turns = result.get("turns") or []
            for item in turns:
                if not isinstance(item, dict):
                    continue
                time = str(item.get("time") or "").strip()
                speaker = str(item.get("speaker") or "未识别发言人").strip()
                text = str(item.get("text") or "").strip()
                if text:
                    lines.extend(["", f"- `[{time}]` **{speaker}**：{text}"])
            return "\n".join(lines).strip()

        if result.get("overview"):
            lines.extend(["", "## 概览", "", str(result["overview"])])
        if normalized == "chat":
            QwenConversationAnalyst._section_objects(
                lines, "参与者与立场", result.get("participants"), "name", "position"
            )
            QwenConversationAnalyst._section_objects(
                lines, "话题时间线", result.get("timeline"), "time", "summary", "topic"
            )
        QwenConversationAnalyst._section_list(lines, "核心观点", result.get("keyPoints"))
        if normalized == "chat":
            QwenConversationAnalyst._section_list(lines, "共识", result.get("agreements"))
            QwenConversationAnalyst._section_list(lines, "分歧", result.get("disagreements"))
        QwenConversationAnalyst._section_list(lines, "决定事项", result.get("decisions"))
        QwenConversationAnalyst._append_actions(lines, result.get("actionItems"))
        QwenConversationAnalyst._section_list(lines, "未解决问题", result.get("openQuestions"))
        if normalized == "chat":
            quotes = result.get("quotes") or []
            if quotes:
                lines.extend(["", "## 重要原话", ""])
                for item in quotes:
                    lines.append(
                        f"- [{item.get('time', '')}] **{item.get('speaker', '')}**："
                        f"{item.get('text', '')}"
                    )
        return "\n".join(lines).strip()

    @staticmethod
    def _append_actions(lines: list[str], actions) -> None:
        actions = actions or []
        if not actions:
            return
        lines.extend(["", "## 后续行动", ""])
        for item in actions:
            if not isinstance(item, dict):
                continue
            owner = item.get("owner") or "未指定"
            deadline = item.get("deadline") or "未指定"
            lines.append(f"- [ ] {item.get('task', '')}（负责人：{owner}；期限：{deadline}）")

    @staticmethod
    def _section_list(lines: list[str], title: str, values) -> None:
        values = values or []
        if values:
            lines.extend(["", f"## {title}", ""])
            lines.extend(f"- {value}" for value in values)

    @staticmethod
    def _section_objects(
        lines: list[str],
        title: str,
        values,
        label_key: str,
        text_key: str,
        prefix_key: str = "",
    ) -> None:
        values = values or []
        if values:
            lines.extend(["", f"## {title}", ""])
            for item in values:
                prefix = f"{item.get(prefix_key)} · " if prefix_key and item.get(prefix_key) else ""
                lines.append(f"- **{prefix}{item.get(label_key, '')}**：{item.get(text_key, '')}")

    @staticmethod
    def _time(milliseconds: int) -> str:
        seconds = max(0, milliseconds // 1000)
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    def _transcript_line(self, item: ResolvedUtterance) -> str:
        return (
            f"[{self._time(item.start_ms)}-{self._time(item.end_ms)}] "
            f"{item.display_name}: {item.text}"
        )
