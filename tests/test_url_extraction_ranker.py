from app.services.url_extraction.extractors import ContentCandidate
from app.services.url_extraction.ranker import rank_candidates


def test_rank_prefers_longer_low_noise_candidate() -> None:
    noisy = ContentCandidate(
        extractor_name="trafilatura",
        title="标题",
        content="相关阅读 点击查看",
        text_len=8,
        paragraph_count=1,
        link_density=0.8,
        chinese_ratio=1.0,
        noise_hits=["相关阅读", "点击查看"],
    )
    clean = ContentCandidate(
        extractor_name="readability",
        title="标题",
        content="这是正文第一段。\n\n这是正文第二段，包含更多事实内容。",
        text_len=28,
        paragraph_count=2,
        link_density=0.1,
        chinese_ratio=1.0,
        noise_hits=[],
    )
    ranked = rank_candidates([noisy, clean], title_hint="标题")
    assert ranked.best is not None
    assert ranked.best.extractor_name == "readability"
    assert ranked.fallback_needed is False


def test_rank_requests_fallback_for_empty_candidates() -> None:
    ranked = rank_candidates([], title_hint="标题")
    assert ranked.best is None
    assert ranked.fallback_needed is True
    assert ranked.confidence == "low"
