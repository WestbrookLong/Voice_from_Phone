from chastream.analysis import QwenConversationAnalyst
from chastream.models import ResolvedUtterance


def test_inferred_transcript_line_includes_voiceprint_candidates():
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
        confidence="inferred",
        best_candidate_name="test",
        second_candidate_name="龙建瑜",
    )

    line = QwenConversationAnalyst()._transcript_line(item)

    assert "身份为上下文推断" in line
    assert "test 0.6505" in line
    assert "龙建瑜 0.6284" in line
