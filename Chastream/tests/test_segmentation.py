from chastream.dialogue import DialogueResolver, join_timed_words
from chastream.models import AudioSegment, TimedWord
from chastream.segmentation import SpeakerTimelineSegmenter


class FakeEmbeddingProvider:
    pass


def test_overlapping_scl_candidates_are_merged():
    segmenter = SpeakerTimelineSegmenter(FakeEmbeddingProvider(), merge_distance_ms=800)

    assert segmenter.merge_candidates([5000, 5420, 12000, 12750]) == [5210, 12375]


def test_words_are_assigned_by_midpoint_and_keep_punctuation():
    records = [
        {"segment": AudioSegment("s1", 0, 1000, "a.wav")},
        {"segment": AudioSegment("s2", 1000, 2200, "b.wav")},
    ]
    first = TimedWord("w1", 100, 800, "甲说", "。")
    second = TimedWord("w2", 1100, 2000, "乙说", "！")

    assert DialogueResolver._record_for_time(records, 450)["segment"].id == "s1"
    assert DialogueResolver._record_for_time(records, 1550)["segment"].id == "s2"
    assert join_timed_words([first, second]) == "甲说。乙说！"
