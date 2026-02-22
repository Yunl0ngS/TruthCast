from app.schemas.detect import ClaimItem
from app.services import pipeline
from app.services.web_retrieval import WebEvidenceCandidate


def test_retrieve_evidence_web_only(monkeypatch) -> None:
    claim = ClaimItem(
        claim_id="c1",
        claim_text="官方通报称某指标为3%，并给出来源链接。",
        source_sentence="官方通报称某指标为3%，并给出来源链接。",
    )

    web = WebEvidenceCandidate(
        title="联网检索到的权威条目",
        source="gov.cn",
        url="https://www.gov.cn/live",
        published_at="2026-02-10",
        summary="联网实时条目摘要",
        relevance=0.86,
        raw_snippet="联网实时条目摘要",
        domain="governance",
        is_authoritative=True,
    )

    monkeypatch.setattr("app.services.pipeline.search_web_evidence", lambda text, top_k=6: [web])

    rows = pipeline.retrieve_evidence([claim])
    assert len(rows) == 1
    assert rows[0].source_type == "web_live"
    assert rows[0].domain == "governance"
    assert rows[0].source == "gov.cn"
