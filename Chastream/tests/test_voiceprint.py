import numpy as np

from chastream.models import SpeakerCollection, VoiceElement
from chastream.voiceprint import VoiceprintService, cosine_similarity


class FakeProvider:
    model_id = "fake"


class FakeRepository:
    pass


def element(element_id, name, vector, *, hidden=False):
    return VoiceElement(
        id=element_id,
        name=name,
        model_id="fake",
        centroid=vector,
        hidden=hidden,
    )


def collection(collection_id, name, *elements):
    return SpeakerCollection(
        id=collection_id,
        name=name,
        elements=list(elements),
    )


def test_cosine_similarity_uses_normalized_embeddings():
    assert cosine_similarity([2, 0], [10, 0]) == 1.0


def test_collection_uses_best_active_element_for_matching():
    service = VoiceprintService(provider=FakeProvider(), repository=FakeRepository())
    collections = [
        collection(
            "person-a",
            "甲",
            element("a-weak", "旧声音", [0.4, 0.6]),
            element("a-strong", "日常声音", [1.0, 0.0]),
        ),
        collection(
            "person-b",
            "乙",
            element("b-main", "默认声音", [0.0, 1.0]),
        ),
    ]

    result = service.match(
        np.array([0.95, 0.05]),
        collections,
        threshold=0.3,
        required_margin=0.1,
    )

    assert result.profile_id == "person-a"
    assert result.best_element_id == "a-strong"
    assert result.collection_scores[0]["bestElementId"] == "a-strong"


def test_hidden_element_is_excluded_from_collection_max():
    service = VoiceprintService(provider=FakeProvider(), repository=FakeRepository())
    collections = [
        collection(
            "person-a",
            "甲",
            element("a-hidden", "隐藏声音", [1.0, 0.0], hidden=True),
            element("a-active", "启用声音", [0.0, 1.0]),
        ),
        collection(
            "person-b",
            "乙",
            element("b-main", "默认声音", [0.9, 0.1]),
        ),
    ]

    result = service.match(
        np.array([1.0, 0.0]),
        collections,
        threshold=0.3,
        required_margin=0.1,
    )

    assert result.profile_id == "person-b"
    assert result.best_element_id == "b-main"


def test_ambiguous_collection_match_remains_unknown():
    service = VoiceprintService(provider=FakeProvider(), repository=FakeRepository())
    collections = [
        collection("person-a", "甲", element("a", "日常", [1.0, 0.0])),
        collection("person-b", "乙", element("b", "日常", [0.98, 0.02])),
    ]

    result = service.match(
        np.array([1.0, 0.0]),
        collections,
        threshold=0.3,
        required_margin=0.1,
    )

    assert result.accepted is False
    assert result.profile_id is None
    assert result.best_candidate_name == "甲"
    assert result.second_candidate_name == "乙"


def test_selected_candidate_below_match_threshold_remains_unknown():
    service = VoiceprintService(provider=FakeProvider(), repository=FakeRepository())
    collections = [
        collection("person-a", "甲", element("a", "日常", [1.0, 0.0]))
    ]

    result = service.match(
        np.array([0.2, 0.98]),
        collections,
        threshold=0.33,
        required_margin=0.06,
    )

    assert result.score < 0.33
    assert result.accepted is False
    assert result.profile_id is None
    assert result.display_name == "未识别发言人"
