from app.schemas.detect import EvidenceItem
from app.services.evidence_summarization import summarize_evidence_for_claim


def test_summary_disabled_returns_original(monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_EVIDENCE_SUMMARY_ENABLED", "false")
    rows = [
        EvidenceItem(
            evidence_id="e1",
            claim_id="c1",
            title="t1",
            source="s1",
            url="https://a.com/1",
            published_at="2026-02-15",
            summary="x",
            stance="support",
            source_weight=0.7,
            source_type="web_live",
        )
    ]
    out = summarize_evidence_for_claim("claim", rows)
    assert out == rows


def test_summary_enabled_uses_llm_output(monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_EVIDENCE_SUMMARY_ENABLED", "true")
    monkeypatch.setenv("TRUTHCAST_LLM_API_KEY", "dummy")

    rows = [
        EvidenceItem(
            evidence_id="e1",
            claim_id="c1",
            title="t1",
            source="s1",
            url="https://a.com/1",
            published_at="2026-02-15",
            summary="x1",
            stance="support",
            source_weight=0.7,
            source_type="web_live",
        ),
        EvidenceItem(
            evidence_id="e2",
            claim_id="c1",
            title="t2",
            source="s2",
            url="https://a.com/2",
            published_at="2026-02-15",
            summary="x2",
            stance="support",
            source_weight=0.6,
            source_type="web_live",
        ),
    ]

    fake_payload = {
        "summaries": [
            {
                "summary_text": "综合结论：该说法有权威来源支持。",
                "stance_hint": "support",
                "confidence": 0.8,
                "source_indices": [0, 1],
            }
        ]
    }
    monkeypatch.setattr(
        "app.services.evidence_summarization._call_summary_llm",
        lambda claim_text, evidences, api_key, target_min, target_max: fake_payload,
    )

    out = summarize_evidence_for_claim("claim", rows)
    assert len(out) == 1
    assert out[0].source_type == "web_summary"
    assert out[0].stance == "support"
    assert "综合结论" in out[0].summary

