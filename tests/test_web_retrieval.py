from app.services.web_retrieval import WebEvidenceCandidate, search_web_evidence


def test_web_retrieval_disabled(monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_WEB_RETRIEVAL_ENABLED", "false")
    rows = search_web_evidence("官方通报称某指标为3%")
    assert rows == []


def test_web_retrieval_baidu_parse(monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_WEB_RETRIEVAL_ENABLED", "true")
    monkeypatch.setenv("TRUTHCAST_WEB_SEARCH_PROVIDER", "baidu")
    monkeypatch.setenv("TRUTHCAST_WEB_SEARCH_API_KEY", "dummy")
    monkeypatch.setenv("TRUTHCAST_WEB_ALLOWED_DOMAINS", "news.cctv.com,www.xinhuanet.com")

    def fake_search_baidu(claim_text: str, top_k: int, timeout_sec: float):
        _ = claim_text, top_k, timeout_sec
        return [
            {
                "title": "央视新闻：权威通报",
                "url": "https://news.cctv.com/2026/02/10/abc.shtml",
                "summary": "通报明确指出相关数据来源与时间范围。",
                "score": 0.8,
                "published_at": "2026-02-09",
                "raw_snippet": "通报明确指出相关数据来源与时间范围。",
            },
            {
                "title": "非白名单来源",
                "url": "https://example.com/post",
                "summary": "无关内容",
                "score": 0.9,
                "published_at": "2026-02-09",
                "raw_snippet": "无关内容",
            },
        ]

    monkeypatch.setattr("app.services.web_retrieval._search_baidu_api", fake_search_baidu)
    rows = search_web_evidence("官方通报称某指标为3%")

    assert len(rows) == 1
    assert isinstance(rows[0], WebEvidenceCandidate)
    assert rows[0].source == "news.cctv.com"
    assert rows[0].is_authoritative is False
