from __future__ import annotations

import json
import os
from pathlib import Path

import requests

from .chastream_core.transcription import (
    DashScopeTemporaryUploader,
    ParaformerTimestampProvider,
)


QWEN_ENDPOINT = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"


def process_quick_note(audio_path: Path, style: str, metadata: dict | None = None) -> dict:
    uploader = DashScopeTemporaryUploader(model="paraformer-v2")
    provider = ParaformerTimestampProvider(model="paraformer-v2")
    uploaded_url = uploader.upload(audio_path)
    task_id = provider.submit(uploaded_url)
    task = provider.wait(task_id)
    raw, sentences, _ = provider.fetch_transcription(task["transcription_url"])
    transcript = "\n".join(item.text for item in sentences if item.text).strip()
    if not transcript:
        raise RuntimeError("录音中没有识别到有效文本。")
    context = metadata or {}
    existing_title = str(context.get("existingTitle") or "").strip()
    existing_summary = str(context.get("existingSummary") or "").strip()
    existing_content = str(context.get("existingContent") or "").strip()
    processing_mode = str(context.get("processingMode") or "organize")
    if processing_mode == "transcribe":
        content = _append(existing_content, transcript)
        result = {
            "title": existing_title or _fallback_title(transcript),
            "summary": existing_summary,
            "content": content,
        }
    else:
        result = organize_note(
            transcript,
            style,
            existing_title=existing_title,
            existing_summary=existing_summary,
            existing_content=existing_content,
        )
    result["rawTranscript"] = transcript
    result["transcription"] = raw
    return result


def organize_note(
    transcript: str,
    style: str,
    *,
    existing_title: str = "",
    existing_summary: str = "",
    existing_content: str = "",
) -> dict:
    api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("DASHSCOPE_API_KEY is not configured.")
    response = requests.post(
        QWEN_ENDPOINT,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": os.environ.get("CHASTREAM_QWEN_MODEL", "qwen-plus"),
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是 Chastream 想法整理助手。将口语转写整理成可长期保存的中文笔记。"
                        "不得捏造信息。输出严格 JSON，字段为 title、summary、content。"
                        "title 不超过20字；summary 是 Widget 使用的一到两句摘要，不超过80字；"
                        "content 只能是本次新增语音整理后的新增段落，不得重写已有正文；"
                        "summary 根据已有正文与新增段落概括整篇笔记。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"整理风格：{style}\n"
                        f"已有标题：{existing_title}\n"
                        f"已有摘要：{existing_summary}\n"
                        f"已有正文：\n{existing_content}\n\n"
                        f"本次新增语音转写：\n{transcript}"
                    ),
                },
            ],
        },
        timeout=120,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Qwen HTTP {response.status_code}: {response.text}")
    content = response.json()["choices"][0]["message"]["content"].strip()
    if content.startswith("```"):
        content = "\n".join(content.splitlines()[1:-1]).strip()
    result = json.loads(content)
    for key in ("title", "summary", "content"):
        if not str(result.get(key, "")).strip():
            raise RuntimeError(f"Qwen response is missing {key}.")
    result["title"] = existing_title or str(result["title"]).strip()
    result["content"] = _append(existing_content, str(result["content"]).strip())
    return result


def _append(existing: str, addition: str) -> str:
    parts = [item.strip() for item in (existing, addition) if item.strip()]
    return "\n\n".join(parts)


def _fallback_title(value: str) -> str:
    compact = "".join(value.split())
    return compact[:10] or "新笔记"
