import pytest

from chastream.manager import ChastreamManager
from chastream.models import SessionState, VoiceProfile


def profile(profile_id, name):
    return VoiceProfile(
        id=profile_id,
        name=name,
        model_id="fake",
        centroid=[1.0, 0.0],
    )


class FakeProfiles:
    def __init__(self, profiles):
        self.items = profiles

    def load_all(self):
        return list(self.items)


def test_session_uses_only_selected_registered_profiles():
    manager = ChastreamManager()
    manager.profiles = FakeProfiles(
        [
            profile("person-a", "甲"),
            profile("person-b", "乙"),
            profile("person-c", "丙"),
        ]
    )
    session = SessionState(
        id="session-1",
        title="范围测试",
        selected_speaker_ids=["person-a", "person-b"],
    )

    selected = manager._profiles_for_session(session)

    assert [item.id for item in selected] == ["person-a", "person-b"]


def test_session_creation_rejects_unregistered_profile():
    manager = ChastreamManager()
    manager.profiles = FakeProfiles([profile("person-a", "甲")])

    with pytest.raises(ValueError, match="未注册或已删除"):
        manager._validate_selected_speakers(["person-a", "person-missing"])
