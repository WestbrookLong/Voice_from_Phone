from chastream.analysis import QwenConversationAnalyst
from chastream.analysis_prompts import build_analysis_messages, normalize_analysis_style
from chastream.models import ResolvedUtterance


def test_transcript_line_does_not_add_inferred_identity_evidence():
    item = ResolvedUtterance(
        id="unit-1",
        canonical_speaker_id="person-b",
        display_name="龙建瑜",
        start_ms=5820,
        end_ms=11150,
        text="有时候后半句换人。",
        score=0.6505,
        second_score=0.6284,
        margin=0.0221,
        confidence="unknown",
        best_candidate_name="test",
        second_candidate_name="龙建瑜",
    )

    line = QwenConversationAnalyst()._transcript_line(item)

    assert line == "[00:05-00:11] 龙建瑜: 有时候后半句换人。"
    assert "上下文推断" not in line


def test_formal_paragraph_prompt_uses_style_specific_schema():
    messages = build_analysis_messages("[00:00-00:03] 甲: 测试内容。", "formal_paragraph")
    prompt = messages[1]["content"]

    assert "正式段落" in prompt
    assert '"paragraphs":string[]' in prompt
    assert "未识别发言人" in messages[0]["content"]


def test_unknown_style_falls_back_to_chat():
    assert normalize_analysis_style("not-a-style") == "chat"


def test_style_specific_markdown():
    formal = QwenConversationAnalyst.to_markdown(
        {"title": "整理稿", "paragraphs": ["第一段。", "第二段。"]},
        "formal_paragraph",
    )
    todos = QwenConversationAnalyst.to_markdown(
        {
            "title": "待办",
            "actionItems": [
                {"task": "完成测试", "owner": "甲", "deadline": None},
            ],
        },
        "todo_items",
    )

    assert formal == "# 整理稿\n\n第一段。\n\n第二段。"
    assert "- [ ] 完成测试（负责人：甲；期限：未指定）" in todos
