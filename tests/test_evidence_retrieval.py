from app.services.evidence_retrieval import detect_scenario, infer_stance, load_kb, rank_evidence


def test_load_kb_non_empty() -> None:
    kb = load_kb()
    assert len(kb) >= 3
    assert all(len(item.domains) >= 1 for item in kb)


def test_rank_evidence_returns_candidates() -> None:
    ranked = rank_evidence("Official statement on infection-rate bulletin and public communication.")
    assert len(ranked) >= 1
    best, score = ranked[0]
    assert best.url.startswith("http")
    assert 0.0 <= score <= 1.0


def test_infer_stance_refute_for_risky_claim() -> None:
    kb = load_kb()
    target = next(item for item in kb if item.stance_hint == "refute")
    stance = infer_stance(
        "Shocking internal source says it is 100% true and must share now.",
        target,
        0.6,
    )
    assert stance == "refute"


def test_rank_evidence_for_chinese_claim() -> None:
    ranked = rank_evidence("网传内部消息称必须转发，疑似旧闻翻炒，需要辟谣核验。")
    assert len(ranked) >= 1
    top_titles = [item.title for item, _ in ranked]
    assert any("辟谣" in title or "网信办" in title or "网安" in title for title in top_titles)


def test_detect_scenario() -> None:
    assert detect_scenario("某地卫健委发布感染率通报") in {"health", "governance"}
    assert detect_scenario("公安提示警惕电信诈骗") == "security"
