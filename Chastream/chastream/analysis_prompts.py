from __future__ import annotations


STYLE_LABELS = {
    "chat": "对话分析",
    "meeting_notes": "会议纪要",
    "formal_paragraph": "正式段落",
    "summary_bullets": "摘要要点",
    "todo_items": "待办事项",
    "faithful_cleanup": "忠实清理",
}

STYLE_INSTRUCTIONS = {
    "chat": (
        "完整分析对话结构，区分参与者立场、话题演进、共识、分歧、决定、行动项和重要原话。"
    ),
    "meeting_notes": (
        "整理成简洁会议纪要，突出会议概览、关键结论、讨论要点、决定、行动项和未解决问题。"
    ),
    "formal_paragraph": (
        "将对话整理成书面、正式、连贯的中文段落；删除口头禅、停顿和无意义重复，"
        "保留参与者归属、核心观点和原有逻辑关系。"
    ),
    "summary_bullets": (
        "整理成清晰的摘要要点，每条只表达一个观点，突出结论、理由、限制条件和下一步。"
    ),
    "todo_items": (
        "只提取明确或强暗示的待办事项；尽量保留负责人、任务和截止时间，缺失信息使用 null。"
    ),
    "faithful_cleanup": (
        "按原始时间顺序忠实清理对话，修正口语冗余、断句和明显转写错误；不得总结、扩写或改变立场。"
    ),
}

STYLE_SCHEMAS = {
    "chat": (
        '{"title":string,"overview":string,'
        '"participants":[{"name":string,"position":string}],'
        '"timeline":[{"time":string,"topic":string,"summary":string}],'
        '"keyPoints":string[],"agreements":string[],"disagreements":string[],'
        '"decisions":string[],'
        '"actionItems":[{"owner":string|null,"task":string,"deadline":string|null}],'
        '"openQuestions":string[],'
        '"quotes":[{"speaker":string,"time":string,"text":string}]}'
    ),
    "meeting_notes": (
        '{"title":string,"overview":string,"keyPoints":string[],'
        '"decisions":string[],'
        '"actionItems":[{"owner":string|null,"task":string,"deadline":string|null}],'
        '"openQuestions":string[]}'
    ),
    "formal_paragraph": '{"title":string,"paragraphs":string[]}',
    "summary_bullets": '{"title":string,"bullets":string[]}',
    "todo_items": (
        '{"title":string,'
        '"actionItems":[{"owner":string|null,"task":string,"deadline":string|null}]}'
    ),
    "faithful_cleanup": (
        '{"title":string,'
        '"turns":[{"time":string,"speaker":string,"text":string}]}'
    ),
}


def normalize_analysis_style(value: str | None) -> str:
    style = str(value or "").strip()
    return style if style in STYLE_LABELS else "chat"


def build_analysis_messages(transcript: str, style: str) -> list[dict[str, str]]:
    normalized = normalize_analysis_style(style)
    system = (
        "你是 Chastream 的中文对话整理 Agent。输入是带时间戳和说话人身份的完整对话。"
        "必须忠实于原文，不得编造人物、事实、观点、决定、负责人、期限或因果关系。"
        "不同说话人的观点必须正确归属；“未识别发言人”必须保持该标签，不得根据语义猜测身份。"
        "允许修正明显的语音转写错误、标点和断句。"
        "只输出合法 JSON object，不要输出 Markdown 代码块或解释文字。"
    )
    user = (
        f"整理风格：{STYLE_LABELS[normalized]}\n"
        f"风格要求：{STYLE_INSTRUCTIONS[normalized]}\n\n"
        f"严格按照以下 JSON 结构输出：\n{STYLE_SCHEMAS[normalized]}\n\n"
        "数组没有内容时输出 []；缺失的负责人或截止时间使用 null。"
        "不得增加原对话没有的信息。\n\n"
        f"完整对话：\n{transcript}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
