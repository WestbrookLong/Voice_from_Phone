import json

import chastream.storage as storage_module
from chastream.storage import SessionRepository


def test_load_history_uses_result_artifacts_for_older_session(monkeypatch, tmp_path):
    monkeypatch.setattr(storage_module, "SESSIONS_ROOT", tmp_path)
    session_id = "20260607-test"
    directory = tmp_path / session_id
    directory.mkdir()
    (directory / "session.json").write_text(
        json.dumps(
            {
                "id": session_id,
                "title": "历史测试",
                "status": "done",
                "legacy_field": "ignored",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (directory / "dialogue.json").write_text(
        json.dumps([{"text": "历史对话"}], ensure_ascii=False),
        encoding="utf-8",
    )
    (directory / "analysis.json").write_text(
        json.dumps({"overview": "历史整理"}, ensure_ascii=False),
        encoding="utf-8",
    )

    session = SessionRepository().load(session_id)

    assert session.title == "历史测试"
    assert session.resolved_utterances == [{"text": "历史对话"}]
    assert session.analysis == {"overview": "历史整理"}
