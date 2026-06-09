from chastream.analysis import QwenConversationAnalyst
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
