import json

from app.services import claim_extraction


def test_rule_based_fallback_when_llm_disabled(monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_LLM_ENABLED", "false")
    monkeypatch.setenv("TRUTHCAST_CLAIM_METHOD", "default")
    claims = claim_extraction.extract_claims("Official statement says rate is 3% on 2026-02-09.")
    assert len(claims) >= 1
    assert claims[0].claim_id == "c1"


def test_llm_path_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_LLM_ENABLED", "true")
    monkeypatch.setenv("TRUTHCAST_LLM_API_KEY", "dummy")
    monkeypatch.setenv("TRUTHCAST_CLAIM_METHOD", "default")

    def _fake_call_llm(text: str, api_key: str, max_items: int | None = None) -> str:
        _ = text, api_key, max_items
        return json.dumps(
            {
                "claims": [
                    {
                        "claim_text": "Infection rate is 3%",
                        "entity": "health authority",
                        "time": "2026-02-09",
                        "location": "city-a",
                        "value": "3%",
                        "source_sentence": "The infection rate is 3%.",
                    }
                ]
            }
        )

    monkeypatch.setattr(claim_extraction, "_call_llm", _fake_call_llm)
    claims = claim_extraction.extract_claims("Some input text")
    assert len(claims) == 1
    assert claims[0].claim_text == "Infection rate is 3%"
    assert claims[0].value == "3%"


def test_llm_claim_normalization_and_dedup(monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_LLM_ENABLED", "true")
    monkeypatch.setenv("TRUTHCAST_LLM_API_KEY", "dummy")
    monkeypatch.setenv("TRUTHCAST_CLAIM_METHOD", "default")

    def _fake_call_llm(text: str, api_key: str, max_items: int | None = None) -> str:
        _ = text, api_key, max_items
        return json.dumps(
            {
                "claims": [
                    {
                        "claim_text": "The infection rate is 3%.",
                        "entity": "Health Bureau   ",
                        "time": "2026/2/9",
                        "location": " City-A ",
                        "value": "about 3%",
                        "source_sentence": "The infection rate is 3% on 2026/2/9 in City-A.",
                    },
                    {
                        "claim_text": "The infection rate is 3%.",
                        "entity": "",
                        "time": "",
                        "location": "",
                        "value": "",
                        "source_sentence": "Duplicate sentence",
                    },
                ]
            }
        )

    monkeypatch.setattr(claim_extraction, "_call_llm", _fake_call_llm)
    claims = claim_extraction.extract_claims("Some input text")
    assert len(claims) == 1
    assert claims[0].claim_id == "c1"
    assert claims[0].entity == "Health Bureau"
    assert claims[0].time == "2026-02-09"
    assert claims[0].location == "City-A"
    assert claims[0].value == "3%"


def test_rule_based_filters_non_verifiable_sentence(monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_LLM_ENABLED", "false")
    monkeypatch.setenv("TRUTHCAST_CLAIM_METHOD", "default")
    claims = claim_extraction.extract_claims("I think this is terrible. Maybe something happened.")
    assert len(claims) == 1
    assert claims[0].claim_text == "I think this is terrible. Maybe something happened."


def test_claim_max_items_limit(monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_LLM_ENABLED", "false")
    monkeypatch.setenv("TRUTHCAST_CLAIM_METHOD", "default")
    monkeypatch.setenv("TRUTHCAST_CLAIM_MAX_ITEMS", "3")
    text = (
        "官方通报称A指标为3%并发布于2026-02-09。"
        "官方通报称B指标为4%并发布于2026-02-09。"
        "官方通报称C指标为5%并发布于2026-02-09。"
        "官方通报称D指标为6%并发布于2026-02-09。"
        "官方通报称E指标为7%并发布于2026-02-09。"
    )
    claims = claim_extraction.extract_claims(text)
    assert len(claims) == 3
    assert claims[0].claim_id == "c1"
    assert claims[-1].claim_id == "c3"


def test_claim_scoring_prefers_verifiable_items(monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_LLM_ENABLED", "false")
    monkeypatch.setenv("TRUTHCAST_CLAIM_METHOD", "default")
    monkeypatch.setenv("TRUTHCAST_CLAIM_MAX_ITEMS", "1")
    text = (
        "有人说这件事很离谱。"
        "卫健委通报称感染率为3%，时间为2026-02-09。"
    )
    claims = claim_extraction.extract_claims(text)
    assert len(claims) == 1
    assert "感染率为3%" in claims[0].claim_text
