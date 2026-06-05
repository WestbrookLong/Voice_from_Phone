from __future__ import annotations


STYLE_LABELS = {
    "formal_paragraph": "Formal paragraph",
    "faithful_cleanup": "Faithful cleanup",
    "summary_bullets": "Summary bullets",
    "meeting_notes": "Meeting notes",
    "email_draft": "Email draft",
    "todo_items": "Todo items",
}


STYLE_INSTRUCTIONS = {
    "formal_paragraph": (
        "Rewrite the transcript into polished, formal, coherent Chinese paragraphs. "
        "Remove filler words, repetitions, pauses, and self-corrections. Preserve facts, numbers, names, intent, and stance."
    ),
    "faithful_cleanup": (
        "Clean the transcript lightly. Keep the speaker's original meaning and information density. "
        "Only remove obvious filler words, repeated fragments, and recognition artifacts."
    ),
    "summary_bullets": (
        "Summarize the transcript into concise Chinese bullet points. Keep only important points, conclusions, and context."
    ),
    "meeting_notes": (
        "Turn the transcript into Chinese meeting notes with sections for background, key points, decisions, and action items. "
        "Do not invent decisions or action items that are not supported by the transcript."
    ),
    "email_draft": (
        "Turn the transcript into a clear, professional Chinese email draft. Preserve the user's intent and do not invent details."
    ),
    "todo_items": (
        "Extract concrete action items from the transcript. If there are no clear action items, say so briefly in Chinese."
    ),
}


def normalize_style(style: str | None) -> str:
    value = (style or "formal_paragraph").strip()
    return value if value in STYLE_INSTRUCTIONS else "formal_paragraph"


def build_polish_messages(transcript: str, style: str, glossary: str = "", incremental: bool = False) -> list[dict]:
    normalized_style = normalize_style(style)
    mode = "You are updating a live draft while the user is still recording." if incremental else "This is the final pass."
    glossary_part = f"\nGlossary and preferred terms:\n{glossary.strip()}\n" if glossary.strip() else ""
    system = (
        "You are Flow Voice's Chinese voice-writing agent. "
        "You receive speech recognition text and produce useful written output. "
        "Never add facts that are not present in the transcript. "
        "If ASR text contains obvious recognition errors, correct them only when the context makes the correction safe. "
        "Return only the rewritten content, with no explanations."
    )
    user = (
        f"{mode}\n"
        f"Style: {STYLE_LABELS[normalized_style]}\n"
        f"Instructions: {STYLE_INSTRUCTIONS[normalized_style]}\n"
        f"{glossary_part}\n"
        "Transcript:\n"
        f"{transcript.strip()}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
