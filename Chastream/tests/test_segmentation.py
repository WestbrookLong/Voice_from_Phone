from chastream.dialogue import (
    build_punctuation_units,
    join_timed_words,
    nearest_word_boundary,
)
from chastream.models import TimedWord


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
