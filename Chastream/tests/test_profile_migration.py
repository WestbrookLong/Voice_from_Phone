import json

import chastream.storage as storage_module
from chastream.storage import ProfileRepository


def test_legacy_profile_migrates_to_single_element_collection(monkeypatch, tmp_path):
    monkeypatch.setattr(storage_module, "PROFILES_ROOT", tmp_path)
    legacy = {
        "id": "person-legacy",
        "name": "甲",
        "model_id": "fake",
        "sample_paths": ["sample.wav"],
        "embeddings": [[1.0, 0.0]],
        "centroid": [1.0, 0.0],
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    path = tmp_path / "person-legacy.json"
    path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")

    collections = ProfileRepository().load_all()

    assert len(collections) == 1
    assert collections[0].id == "person-legacy"
    assert collections[0].elements[0].name == "默认声音"
    assert collections[0].elements[0].centroid == [1.0, 0.0]
    migrated = json.loads(path.read_text(encoding="utf-8"))
    assert migrated["schema_version"] == 2
    assert len(migrated["elements"]) == 1
