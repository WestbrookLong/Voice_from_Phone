from __future__ import annotations

import json
import os

import requests

from .models import ResolvedUtterance


QWEN_ENDPOINT = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"


class QwenConversationAnalyst:
    def __init__(self, model: str = "qwen-plus", api_key: str | None = None) -> None:
        self.model = model
        self.api_key = (api_key or os.environ.get("DASHSCOPE_API_KEY", "")).strip()

    def analyze(self, utterances: list[ResolvedUtterance]) -> dict:
        if not self.api_key:
            raise RuntimeError("DASHSCOPE_API_KEY is not configured.")
        transcript = "\n".join(
            f"[{self._time(item.start_ms)}-{self._time(item.end_ms)}] "
            f"{item.display_name}: {item.text}"
            for item in utterances
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "你是 Chastream 的中文对话分析 Agent。输入是带时间戳和说话人身份的完整对话。"
                    "必须忠实于原文，不得编造人物、事实、立场、决定或待办。"
                    "不同说话人的观点必须分别归属；声纹未识别的发言人保持原标签。"
                    "仅输出合法 JSON object，不要输出 Markdown 代码块或解释。"
                ),
            },
            {
                "role": "user",
                "content": (
                    "请把下面完整对话整理为结构化结果。JSON 字段必须为：\n"
                    'title: string；overview: string；participants: [{"name":string,"position":string}]；'
                    'timeline: [{"time":string,"topic":string,"summary":string}]；'
                    "keyPoints: string[]；agreements: string[]；disagreements: string[]；"
                    'decisions: string[]；actionItems: [{"owner":string|null,"task":string,"deadline":string|null}]；'
                    "openQuestions: string[]；"
                    'quotes: [{"speaker":string,"time":string,"text":string}]。\n'
                    "没有证据的字段使用空数组，缺失负责人或期限使用 null。\n\n"
                    f"完整对话：\n{transcript}"
                ),
            },
        ]
        response = requests.post(
            QWEN_ENDPOINT,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={"model": self.model, "messages": messages, "temperature": 0.2},
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
    def to_markdown(result: dict) -> str:
        lines = [f"# {result.get('title') or '对话纪要'}"]
        if result.get("overview"):
            lines.extend(["", "## 概览", "", str(result["overview"])])
        QwenConversationAnalyst._section_objects(lines, "参与者与立场", result.get("participants"), "name", "position")
        QwenConversationAnalyst._section_objects(lines, "话题时间线", result.get("timeline"), "time", "summary", "topic")
        QwenConversationAnalyst._section_list(lines, "核心观点", result.get("keyPoints"))
        QwenConversationAnalyst._section_list(lines, "共识", result.get("agreements"))
        QwenConversationAnalyst._section_list(lines, "分歧", result.get("disagreements"))
        QwenConversationAnalyst._section_list(lines, "决定事项", result.get("decisions"))
        actions = result.get("actionItems") or []
        if actions:
            lines.extend(["", "## 后续行动", ""])
            for item in actions:
                owner = item.get("owner") or "未指定"
                deadline = item.get("deadline") or "未指定"
                lines.append(f"- [ ] {item.get('task', '')}（负责人：{owner}；期限：{deadline}）")
        QwenConversationAnalyst._section_list(lines, "未解决问题", result.get("openQuestions"))
        quotes = result.get("quotes") or []
        if quotes:
            lines.extend(["", "## 重要原话", ""])
            for item in quotes:
                lines.append(f"- [{item.get('time', '')}] **{item.get('speaker', '')}**：{item.get('text', '')}")
        return "\n".join(lines).strip()

    @staticmethod
    def _section_list(lines: list[str], title: str, values) -> None:
        values = values or []
        if values:
            lines.extend(["", f"## {title}", ""])
            lines.extend(f"- {value}" for value in values)

    @staticmethod
    def _section_objects(lines: list[str], title: str, values, label_key: str, text_key: str, prefix_key: str = "") -> None:
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

