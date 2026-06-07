from chastream.transcription import ParaformerTimestampProvider


def test_parses_paraformer_sentence_and_word_timestamps(monkeypatch):
    provider = ParaformerTimestampProvider(api_key="test")

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {
                "transcripts": [
                    {
                        "sentences": [
                            {
                                "sentence_id": 1,
                                "begin_time": 100,
                                "end_time": 800,
                                "text": "你好，开始吧。",
                                "words": [
                                    {
                                        "begin_time": 100,
                                        "end_time": 300,
                                        "text": "你好",
                                        "punctuation": "，",
                                    },
                                    {
                                        "begin_time": 300,
                                        "end_time": 800,
                                        "text": "开始吧",
                                        "punctuation": "。",
                                    },
                                ],
                            }
                        ]
                    }
                ]
            }

    monkeypatch.setattr("chastream.transcription.requests.get", lambda *args, **kwargs: Response())
    raw, sentences, words = provider.fetch_transcription("https://example.invalid/transcription.json")

    assert raw["transcripts"][0]["sentences"][0]["sentence_id"] == 1
    assert len(sentences) == 1
    assert sentences[0].start_ms == 100
    assert sentences[0].end_ms == 800
    assert sentences[0].text == "你好，开始吧。"
    assert [word.text for word in words] == ["你好", "开始吧"]
    assert [word.punctuation for word in words] == ["，", "。"]


def test_wait_extracts_transcription_url(monkeypatch):
    provider = ParaformerTimestampProvider(api_key="test")

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {
                "output": {
                    "task_status": "SUCCEEDED",
                    "results": [{"transcription_url": "https://example.invalid/result.json"}],
                }
            }

    monkeypatch.setattr("chastream.transcription.requests.post", lambda *args, **kwargs: Response())

    output = provider.wait("task-1", poll_seconds=0)

    assert output["transcription_url"] == "https://example.invalid/result.json"
