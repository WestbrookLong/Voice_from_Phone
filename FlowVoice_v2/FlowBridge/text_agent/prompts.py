from __future__ import annotations

import json


STYLE_LABELS = {
    "formal_paragraph": "正式段落",
    "meeting_notes": "会议纪要",
    "summary_bullets": "摘要要点",
    "todo_items": "待办事项",
    "faithful_cleanup": "忠实清理",
}

STYLE_INSTRUCTIONS = {
    "formal_paragraph": "整理成书面、正式、连贯的中文段落，删除口头禅和重复表达，保留核心观点。",
    "meeting_notes": "整理成会议纪要，包含主题、关键结论、讨论要点和后续行动；不要编造未出现的信息。",
    "summary_bullets": "整理成清晰的要点列表，突出结论、原因和下一步。",
    "todo_items": "提取待办事项，尽量包含负责人、动作、对象和截止时间；缺失的信息标注为未提及。",
    "faithful_cleanup": "只做忠实清理，修正口语冗余、断句和明显错别字，不改变原意和结构。",
}


def normalize_style(value: str | None) -> str:
    key = str(value or "").strip()
    return key if key in STYLE_INSTRUCTIONS else "meeting_notes"


def _system_prompt() -> str:
    return (
        "你是 FlowVoice 的文本整理 agent。用户会用语音输入法产生口语化文本，"
        "你需要把它整理为可直接使用的文本。必须忠实于原文，不要补充未出现的事实。"
    )


def build_segment_prompt(
    previous_summaries: list[dict],
    previous_raw_text: str,
    new_raw_text: str,
    style: str,
) -> list[dict[str, str]]:
    normalized = normalize_style(style)
    summaries = json.dumps(previous_summaries, ensure_ascii=False, indent=2) if previous_summaries else "（暂无）"
    user = (
        "任务：分段整理实时草稿。\n"
        f"整理风格：{STYLE_LABELS[normalized]}\n"
        f"要求：{STYLE_INSTRUCTIONS[normalized]}\n\n"
        "此前分段整理结果：\n"
        f"{summaries}\n\n"
        "此前完整原文：\n"
        f"{previous_raw_text.strip() or '（暂无）'}\n\n"
        "本次新增原文：\n"
        f"{new_raw_text.strip()}\n\n"
        "请结合此前上下文，只整理本次新增内容。必须只输出合法 JSON 对象，不要使用 Markdown 代码块。\n"
        'JSON 格式：{"title":"主题标题","summary":"本段摘要","keyPoints":["要点"],'
        '"actionItems":[{"text":"待办内容","owner":null,"deadline":null}]}'
    )
    return [{"role": "system", "content": _system_prompt()}, {"role": "user", "content": user}]


def build_global_prompt(raw_text: str, segment_summaries: list[dict], style: str) -> list[dict[str, str]]:
    normalized = normalize_style(style)
    summaries = json.dumps(segment_summaries, ensure_ascii=False, indent=2) if segment_summaries else "（暂无）"
    user = (
        "任务：全局整理最终结果。\n"
        f"整理风格：{STYLE_LABELS[normalized]}\n"
        f"要求：{STYLE_INSTRUCTIONS[normalized]}\n\n"
        "此前全部分段整理结果：\n"
        f"{summaries}\n\n"
        "全量原始文本：\n"
        f"{raw_text.strip()}\n\n"
        "请基于全量原文，并参考分段整理结果，输出最终可直接插入电脑光标处的文本。"
    )
    return [{"role": "system", "content": _system_prompt()}, {"role": "user", "content": user}]


def build_prompt(raw_text: str, style: str, *, incremental: bool) -> list[dict[str, str]]:
    if incremental:
        return build_segment_prompt([], "", raw_text, style)
    return build_global_prompt(raw_text, [], style)
