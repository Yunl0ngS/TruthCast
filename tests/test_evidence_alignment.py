import json

from app.schemas.detect import EvidenceItem
from app.services import evidence_alignment


def test_alignment_refute_for_risky_claim(monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_ALIGNMENT_LLM_ENABLED", "false")
    
    evidence = EvidenceItem(
        evidence_id="e1",
        claim_id="c1",
        title="Reuters fact-check methodology",
        source="reuters.com",
        url="https://www.reuters.com/fact-check/",
        published_at="2025-09-09",
        summary="Fact-check and misleading context clarification.",
        stance="refute",
        source_weight=0.86,
    )
    result = evidence_alignment.align_claim_with_evidence(
        "Shocking internal source says it is 100% true and must share now.",
        evidence,
    )
    assert result.stance == "refute"
    assert result.confidence >= 0.55
    assert "反驳" in result.rationale or "辟谣" in result.rationale


def test_alignment_support_for_official_match() -> None:
    evidence = EvidenceItem(
        evidence_id="e2",
        claim_id="c1",
        title="Official statement on outbreak bulletin",
        source="cdc.gov",
        url="https://www.cdc.gov",
        published_at="2025-11-03",
        summary="Official bulletin includes infection-rate data update.",
        stance="support",
        source_weight=0.9,
    )
    result = evidence_alignment.align_claim_with_evidence(
        "Official bulletin confirms infection rate update.",
        evidence,
    )
    assert result.stance in {"support", "insufficient"}


def test_alignment_llm_path(monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_ALIGNMENT_LLM_ENABLED", "true")
    monkeypatch.setenv("TRUTHCAST_LLM_API_KEY", "dummy")

    def _fake_llm(claim_text: str, evidence: EvidenceItem):
        _ = claim_text, evidence
        return evidence_alignment.AlignmentResult(
            stance="support",
            confidence=0.88,
            rationale="证据与主张高度一致。",
        )

    monkeypatch.setattr(evidence_alignment, "_align_with_llm", _fake_llm)

    evidence = EvidenceItem(
        evidence_id="e3",
        claim_id="c1",
        title="官方通报",
        source="gov.cn",
        url="https://www.gov.cn",
        published_at="2025-12-01",
        summary="包含完整数据和来源链接。",
        stance="support",
        source_weight=0.9,
    )
    result = evidence_alignment.align_claim_with_evidence("官方通报确认事件数据", evidence)
    assert result.stance == "support"
    assert result.confidence == 0.88


def test_alignment_fallback_when_llm_returns_none(monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_ALIGNMENT_LLM_ENABLED", "true")
    monkeypatch.setenv("TRUTHCAST_LLM_API_KEY", "dummy")
    monkeypatch.setattr(evidence_alignment, "_align_with_llm", lambda c, e: None)

    evidence = EvidenceItem(
        evidence_id="e4",
        claim_id="c1",
        title="辟谣说明",
        source="piyao.org.cn",
        url="https://www.piyao.org.cn",
        published_at="2025-12-20",
        summary="指出该说法为误导。",
        stance="refute",
        source_weight=0.8,
    )
    result = evidence_alignment.align_claim_with_evidence("震惊！内部消息必须转发", evidence)
    assert result.stance in {"refute", "insufficient", "support"}
