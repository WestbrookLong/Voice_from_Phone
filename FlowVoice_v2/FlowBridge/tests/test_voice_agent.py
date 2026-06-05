from voice_agent.jobs import VoiceAgentManager
from voice_agent.providers.polish.preview import PreviewPolishProvider


def test_voice_agent_session_lifecycle():
    manager = VoiceAgentManager(polish_provider=PreviewPolishProvider())

    session = manager.start_session("formal_paragraph")
    assert session.status == "recording"

    session = manager.append_transcript(session.id, "嗯 这个 今天 需要 完成 接口联调", replace=True)
    assert session.status == "recording"
    assert "需要 完成 接口联调" in session.draft_text

    session = manager.finalize_session(session.id)
    assert session.status == "done"
    assert session.polished_text == session.draft_text


def test_voice_agent_insert_copies_and_pastes_result():
    events = []
    manager = VoiceAgentManager(
        polish_provider=PreviewPolishProvider(),
        copy_callback=lambda text: events.append(("copy", text)),
        insert_callback=lambda text: events.append(("insert", text)),
    )

    session = manager.start_session()
    manager.append_transcript(session.id, "这是最终文本", replace=True, final=True)
    session = manager.insert_result(session.id)

    assert session.copied is True
    assert session.inserted is True
    assert events[0] == ("copy", "这是最终文本")
    assert events[1] == ("insert", "这是最终文本")


def test_voice_agent_audio_chunk_can_update_transcript():
    manager = VoiceAgentManager(polish_provider=PreviewPolishProvider())
    session = manager.start_session()

    session = manager.append_audio_chunk(session.id, b"1234", transcript_text="需要整理第一段")

    assert session.audio_chunk_count == 1
    assert session.audio_byte_count == 4
    assert "需要整理第一段" in session.raw_transcript
    assert session.draft_text


def test_voice_agent_audio_session_forwards_chunks_to_asr(monkeypatch):
    events = []

    class FakeASR:
        def __init__(self, session_id, on_sentence, on_error):
            self.session_id = session_id
            self.on_sentence = on_sentence
            self.on_error = on_error
            events.append(("init", session_id))

        def start(self):
            events.append(("start", self.session_id))

        def send_audio_frame(self, audio):
            events.append(("audio", audio))
            self.on_sentence("手机端转写")

        def stop(self):
            events.append(("stop", self.session_id))

    monkeypatch.setattr("voice_agent.jobs.DashScopeRealtimeASRSession", FakeASR)

    manager = VoiceAgentManager(polish_provider=PreviewPolishProvider())
    session = manager.start_audio_session()

    session = manager.append_audio_chunk(session.id, b"1234")
    assert ("audio", b"1234") in events
    assert "手机端转写" in session.raw_transcript

    session = manager.finalize_session(session.id)
    assert session.status == "done"
    assert ("stop", session.id) in events
