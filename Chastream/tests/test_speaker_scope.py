import pytest

from chastream.manager import ChastreamManager
from chastream.models import SessionState, SpeakerCollection, VoiceElement


def collection(collection_id, name, *, hidden=False):
    return SpeakerCollection(
        id=collection_id,
        name=name,
        elements=[
            VoiceElement(
                id=f"element-{collection_id}",
                name="默认声音",
                model_id="fake",
                centroid=[1.0, 0.0],
                hidden=hidden,
            )
        ],
    )


class FakeProfiles:
    def __init__(self, collections):
        self.items = collections

    def load_all(self):
        return list(self.items)


def test_session_uses_only_selected_collections_and_snapshot_elements():
    manager = ChastreamManager()
    manager.profiles = FakeProfiles(
        [
            collection("person-a", "甲"),
            collection("person-b", "乙"),
            collection("person-c", "丙"),
        ]
    )
    session = SessionState(
        id="session-1",
        title="范围测试",
        selected_speaker_ids=["person-a", "person-b"],
        selected_voiceprint_elements={
            "person-a": ["element-person-a"],
            "person-b": ["element-person-b"],
        },
    )

    selected = manager._collections_for_session(session)

    assert [item.id for item in selected] == ["person-a", "person-b"]
    assert [item.elements[0].id for item in selected] == [
        "element-person-a",
        "element-person-b",
    ]


def test_validation_snapshots_only_active_elements():
    manager = ChastreamManager()
    active = collection("person-a", "甲")
    active.elements.append(
        VoiceElement(
            id="hidden",
            name="隐藏",
            model_id="fake",
            centroid=[0.0, 1.0],
            hidden=True,
        )
    )
    manager.profiles = FakeProfiles([active])

    selected, snapshot = manager._validate_selected_speakers(["person-a"])

    assert selected == ["person-a"]
    assert snapshot == {"person-a": ["element-person-a"]}


def test_session_creation_rejects_unregistered_collection():
    manager = ChastreamManager()
    manager.profiles = FakeProfiles([collection("person-a", "甲")])

    with pytest.raises(ValueError, match="未注册或已删除"):
        manager._validate_selected_speakers(["person-a", "person-missing"])


def test_collection_without_active_elements_cannot_be_selected():
    manager = ChastreamManager()
    manager.profiles = FakeProfiles([collection("person-a", "甲", hidden=True)])

    with pytest.raises(ValueError, match="没有启用的可用声纹元素"):
        manager._validate_selected_speakers(["person-a"])
