from chastream.dialogue import (
    DialogueResolver,
    build_punctuation_units,
    join_timed_words,
    nearest_word_boundary,
)
from chastream.models import AudioSegment, SpeakerMatch, TimedWord
from chastream.segmentation import SentenceChangeRefiner


def word(index, start, end, text, punctuation="", sentence_id="1"):
    return TimedWord(
        id=f"w{index}",
        start_ms=start,
        end_ms=end,
        text=text,
        punctuation=punctuation,
        sentence_id=sentence_id,
    )


def test_comma_and_sentence_end_create_separate_display_units():
    words = [
        word(1, 100, 500, "这个方案"),
        word(2, 500, 900, "没问题", "，"),
        word(3, 1000, 1400, "但是"),
        word(4, 1400, 2000, "需要验证", "。"),
    ]

    units = build_punctuation_units(words)

    assert [item.text for item in units] == ["这个方案没问题，", "但是需要验证。"]
    assert [(item.start_ms, item.end_ms) for item in units] == [(100, 900), (1000, 2000)]


def test_paraformer_sentence_boundary_also_closes_unit_without_punctuation():
    words = [
        word(1, 100, 800, "第一句", sentence_id="1"),
        word(2, 1200, 1900, "第二句", sentence_id="2"),
    ]

    units = build_punctuation_units(words)

    assert [item.text for item in units] == ["第一句", "第二句"]


def test_scl_candidate_aligns_to_nearest_word_gap():
    words = [
        word(1, 100, 500, "甲"),
        word(2, 550, 900, "继续"),
        word(3, 1200, 1600, "乙"),
    ]

    index, boundary_ms = nearest_word_boundary(words, 1000)

    assert index == 2
    assert boundary_ms == 1050


def test_joined_words_keep_punctuation():
    words = [
        word(1, 100, 800, "甲说", "。"),
        word(2, 1100, 2000, "乙说", "！"),
    ]

    assert join_timed_words(words) == "甲说。乙说！"


def test_resolved_row_keeps_runner_up_and_margin():
    record = {
        "segment": AudioSegment("unit-1", 100, 900, "unit.wav", text="测试。"),
        "match": SpeakerMatch("person-a", "甲", 0.79, 0.31, 0.48, True, "high"),
    }

    resolved = DialogueResolver._to_resolved(record)

    assert resolved.score == 0.79
    assert resolved.second_score == 0.31
    assert resolved.margin == 0.48


def test_unknown_match_stays_unassigned():
    match = SpeakerMatch(
        None,
        "未识别发言人",
        0.6505,
        0.6284,
        0.0221,
        False,
        "low",
        "test",
        "龙建瑜",
    )
    record = {
        "segment": AudioSegment("unit-1", 100, 900, "unit.wav", text="测试。"),
        "match": match,
    }

    resolved = DialogueResolver._to_resolved(record)

    assert resolved.canonical_speaker_id is None
    assert resolved.display_name == "未识别发言人"
    assert resolved.confidence == "low"


def test_high_score_with_insufficient_margin_triggers_ambiguity_refinement():
    resolver = object.__new__(DialogueResolver)
    resolver.threshold = 0.33
    resolver.margin = 0.06

    assert resolver._is_ambiguous_match(
        SpeakerMatch(None, "未识别发言人", 0.71, 0.68, 0.03, False, "low")
    )
    assert not resolver._is_ambiguous_match(
        SpeakerMatch(None, "未识别发言人", 0.30, 0.28, 0.02, False, "low")
    )
    assert not resolver._is_ambiguous_match(
        SpeakerMatch("a", "甲", 0.71, 0.60, 0.11, True, "medium")
    )


def test_forced_ambiguity_probe_bypasses_same_speaker_edge_gate(monkeypatch, tmp_path):
    class Provider:
        def extract(self, path):
            return [1.0, 0.0]

    refiner = SentenceChangeRefiner(
        Provider(),
        minimum_side_ms=500,
        edge_window_ms=700,
        change_probe_threshold=0.24,
    )
    monkeypatch.setattr("chastream.segmentation.slice_wav", lambda *args, **kwargs: args[1])
    monkeypatch.setattr(
        "chastream.segmentation.speech_quality",
        lambda path: {"usable": True},
    )
    monkeypatch.setattr("chastream.segmentation.cosine_similarity", lambda left, right: 0.95)
    monkeypatch.setattr(refiner.locator, "locate", lambda *args, **kwargs: 1.5)

    candidate, diagnostic = refiner.locate(
        tmp_path / "audio.wav",
        0,
        3000,
        tmp_path / "segments",
        "unit",
        force_probe=True,
    )

    assert candidate == 1500
    assert diagnostic["forcedByAmbiguousMatch"] is True
    assert diagnostic["accepted"] is True
