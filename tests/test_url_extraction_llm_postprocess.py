import json
from unittest.mock import MagicMock

from app.services.url_extraction.extractors import ContentCandidate
from app.services.url_extraction.llm_postprocess import (
    postprocess_extracted_content,
    rescue_extracted_candidates,
)


def test_postprocess_returns_none_when_disabled(monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_URL_EXTRACT_LLM_ENABLED", "false")
    result = postprocess_extracted_content(
        title="标题",
        content="正文",
        publish_date="2026-03-22",
        source_url="https://example.com/news",
    )
    assert result is None


def test_postprocess_parses_llm_json(monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_URL_EXTRACT_LLM_ENABLED", "true")
    monkeypatch.setenv("TRUTHCAST_LLM_API_KEY", "test-key")

    payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "title": "清洗后标题",
                            "content": "清洗后的正文",
                            "publish_date": "2026-03-22",
                        },
                        ensure_ascii=False,
                    )
                }
            }
        ]
    }

    class FakeResponse:
        def read(self) -> bytes:
            return json.dumps(payload, ensure_ascii=False).encode("utf-8")

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    monkeypatch.setattr("app.services.url_extraction.llm_postprocess.request.urlopen", lambda *args, **kwargs: FakeResponse())

    result = postprocess_extracted_content(
        title="原始标题",
        content="原始正文",
        publish_date="2026-03-22",
        source_url="https://example.com/news",
    )
    assert result is not None
    assert result.content == "清洗后的正文"


def test_rescue_parses_candidate_payload(monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_URL_EXTRACT_LLM_ENABLED", "true")
    monkeypatch.setenv("TRUTHCAST_LLM_API_KEY", "test-key")
    monkeypatch.setenv("TRUTHCAST_URL_EXTRACT_LLM_MODE", "rescue")

    payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "title": "LLM 挽救标题",
                            "content": "LLM 挽救正文",
                            "publish_date": "2026-03-22",
                        },
                        ensure_ascii=False,
                    )
                }
            }
        ]
    }

    class FakeResponse:
        def read(self) -> bytes:
            return json.dumps(payload, ensure_ascii=False).encode("utf-8")

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    monkeypatch.setattr("app.services.url_extraction.llm_postprocess.request.urlopen", lambda *args, **kwargs: FakeResponse())

    result = rescue_extracted_candidates(
        title="原始标题",
        publish_date="",
        source_url="https://example.com/news",
        candidates=[
            ContentCandidate(
                extractor_name="readability",
                title="原始标题",
                content="候选正文一",
                text_len=5,
                paragraph_count=1,
                link_density=0.1,
                chinese_ratio=1.0,
                noise_hits=[],
            )
        ],
    )
    assert result is not None
    assert result.title == "LLM 挽救标题"
