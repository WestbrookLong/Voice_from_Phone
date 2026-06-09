import numpy as np

from chastream.models import VoiceProfile
from chastream.voiceprint import VoiceprintService, cosine_similarity


class FakeProvider:
    model_id = "fake"


class FakeRepository:
    pass


def profile(profile_id, name, vector):
    return VoiceProfile(id=profile_id, name=name, model_id="fake", centroid=vector)


def test_cosine_similarity_uses_normalized_embeddings():
    assert cosine_similarity([2, 0], [10, 0]) == 1.0


def test_multiple_acoustic_intervals_can_match_same_profile():
    service = VoiceprintService(provider=FakeProvider(), repository=FakeRepository())
    profiles = [profile("person-a", "甲", [1.0, 0.0]), profile("person-b", "乙", [0.0, 1.0])]

    speaker_1 = service.match(np.array([0.95, 0.05]), profiles, threshold=0.3, required_margin=0.1)
    speaker_5 = service.match(np.array([0.90, 0.10]), profiles, threshold=0.3, required_margin=0.1)

    assert speaker_1.profile_id == "person-a"
    assert speaker_5.profile_id == "person-a"


def test_ambiguous_match_remains_unknown():
    service = VoiceprintService(provider=FakeProvider(), repository=FakeRepository())
    profiles = [profile("person-a", "甲", [1.0, 0.0]), profile("person-b", "乙", [0.98, 0.02])]

    result = service.match(np.array([1.0, 0.0]), profiles, threshold=0.3, required_margin=0.1)

    assert result.accepted is False
    assert result.profile_id is None
    assert result.best_candidate_name == "甲"
    assert result.second_candidate_name == "乙"


def test_selected_candidate_below_match_threshold_remains_unknown():
    service = VoiceprintService(provider=FakeProvider(), repository=FakeRepository())
    profiles = [profile("person-a", "甲", [1.0, 0.0])]

    result = service.match(
        np.array([0.2, 0.98]),
        profiles,
        threshold=0.33,
        required_margin=0.06,
    )

    assert result.score < 0.33
    assert result.accepted is False
    assert result.profile_id is None
    assert result.display_name == "未识别发言人"
