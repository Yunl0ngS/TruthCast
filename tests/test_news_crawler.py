from unittest.mock import MagicMock, patch
import os

import httpx

from app.services.news_crawler import CrawledNews, crawl_news_url
from app.services.url_extraction.extractors import ContentCandidate
from app.services.url_extraction.metadata import PageMetadata
from app.services.url_extraction.ranker import RankedCandidate


@patch("app.core.security.validate_url_for_ssrf", side_effect=lambda url: url)
@patch("app.services.news_crawler.fetch_page")
@patch("app.services.news_crawler.extract_metadata")
@patch("app.services.news_crawler.extract_with_readability")
@patch("app.services.news_crawler.extract_with_trafilatura")
@patch("app.services.news_crawler.rank_candidates")
def test_crawl_news_url_prefers_ranked_candidate(
    mock_rank,
    mock_trafilatura,
    mock_readability,
    mock_metadata,
    mock_fetch,
    _mock_validate_url,
):
    mock_fetch.return_value = (
        "https://example.com/news",
        "<html><body><article><p>正文</p></article></body></html>",
    )
    mock_metadata.return_value = PageMetadata(
        title="排名后的标题",
        publish_date="2026-03-22",
        site_name="示例站点",
        canonical_url="https://example.com/news",
        meta_debug={},
    )
    mock_readability.return_value = ContentCandidate(
        extractor_name="readability",
        title="候选标题",
        content="这是最终正文。\n\n第二段。",
        text_len=13,
        paragraph_count=2,
        link_density=0.1,
        chinese_ratio=0.8,
        noise_hits=[],
    )
    mock_trafilatura.return_value = ContentCandidate(
        extractor_name="trafilatura",
        title="备用标题",
        content="较差正文",
        text_len=4,
        paragraph_count=1,
        link_density=0.6,
        chinese_ratio=0.8,
        noise_hits=["相关阅读"],
    )
    mock_rank.return_value = RankedCandidate(
        best=mock_readability.return_value,
        confidence="medium",
        score=2.1,
        fallback_needed=False,
        reasons=["正文长度偏短但可判定"],
    )

    result = crawl_news_url("https://example.com/news")

    assert result.success is True
    assert result.title == "排名后的标题"
    assert "最终正文" in result.content
    assert result.publish_date == "2026-03-22"


@patch("app.core.security.validate_url_for_ssrf", side_effect=lambda url: url)
@patch("app.services.news_crawler.fetch_page")
def test_crawl_news_url_http_error(mock_fetch, _mock_validate_url):
    mock_fetch.side_effect = httpx.HTTPStatusError(
        "404 Not Found",
        request=MagicMock(),
        response=MagicMock(),
    )

    result = crawl_news_url("https://example.com/404")

    assert result.success is False
    assert "404" in result.error_msg
    assert result.source_url == "https://example.com/404"


@patch("app.core.security.validate_url_for_ssrf", side_effect=lambda url: url)
@patch("app.services.news_crawler.fetch_page")
@patch("app.services.news_crawler.extract_metadata")
@patch("app.services.news_crawler.extract_with_readability")
@patch("app.services.news_crawler.extract_with_trafilatura")
@patch("app.services.news_crawler.rank_candidates")
def test_crawl_news_url_returns_failed_when_no_candidate(
    mock_rank,
    mock_trafilatura,
    mock_readability,
    mock_metadata,
    mock_fetch,
    _mock_validate_url,
):
    mock_fetch.return_value = ("https://example.com/empty", "<html><body>empty</body></html>")
    mock_metadata.return_value = PageMetadata(
        title="标题",
        publish_date="",
        site_name="",
        canonical_url="https://example.com/empty",
        meta_debug={},
    )
    mock_readability.return_value = None
    mock_trafilatura.return_value = None
    mock_rank.return_value = RankedCandidate(
        best=None,
        confidence="low",
        score=0.0,
        fallback_needed=True,
        reasons=["无可用候选"],
    )

    result = crawl_news_url("https://example.com/empty")

    assert result.success is False
    assert result.content == "[提取失败]"
    assert "无可用候选" in result.error_msg


@patch("app.core.security.validate_url_for_ssrf", side_effect=lambda url: url)
@patch("app.services.news_crawler.fetch_page")
@patch("app.services.news_crawler.extract_metadata")
@patch("app.services.news_crawler.extract_with_readability")
@patch("app.services.news_crawler.extract_with_trafilatura")
@patch("app.services.news_crawler.rank_candidates")
def test_crawl_news_url_logs_fetch_summary(
    mock_rank,
    mock_trafilatura,
    mock_readability,
    mock_metadata,
    mock_fetch,
    _mock_validate_url,
):
    mock_fetch.return_value = ("https://example.com/news", "<html><body><article>正文</article></body></html>")
    mock_metadata.return_value = PageMetadata(
        title="日志标题",
        publish_date="2026-03-22",
        site_name="站点",
        canonical_url="https://example.com/news",
        meta_debug={},
    )
    mock_readability.return_value = ContentCandidate(
        extractor_name="readability",
        title="日志标题",
        content="正文第一段。\n\n正文第二段。",
        text_len=13,
        paragraph_count=2,
        link_density=0.1,
        chinese_ratio=0.8,
        noise_hits=[],
    )
    mock_trafilatura.return_value = None
    mock_rank.return_value = RankedCandidate(
        best=mock_readability.return_value,
        confidence="medium",
        score=2.0,
        fallback_needed=False,
        reasons=["具备基本段落结构"],
    )

    with patch("app.services.news_crawler.logger.info") as mock_info:
        result = crawl_news_url("https://example.com/news")

    assert result.success is True
    logged = " | ".join(str(call) for call in mock_info.call_args_list)
    assert "开始抓取新闻链接" in logged
    assert "HTTP获取成功" in logged
    assert "metadata提取完成" in logged
    assert "候选正文打分完成" in logged


@patch("app.core.security.validate_url_for_ssrf", side_effect=lambda url: url)
@patch("app.services.news_crawler.fetch_page")
@patch("app.services.news_crawler.extract_metadata")
@patch("app.services.news_crawler.extract_with_readability")
@patch("app.services.news_crawler.extract_with_trafilatura")
@patch("app.services.news_crawler.rank_candidates")
@patch("app.services.news_crawler.render_page")
def test_crawl_news_url_uses_rendered_fallback_when_ranked_low(
    mock_render,
    mock_rank,
    mock_trafilatura,
    mock_readability,
    mock_metadata,
    mock_fetch,
    _mock_validate_url,
):
    os.environ["TRUTHCAST_URL_EXTRACT_RENDER_FALLBACK"] = "true"
    mock_fetch.return_value = ("https://example.com/news", "<html><body>空壳页面</body></html>")
    mock_metadata.side_effect = [
        PageMetadata(title="原始标题", publish_date="", site_name="", canonical_url="https://example.com/news", meta_debug={}),
        PageMetadata(title="渲染标题", publish_date="2026-03-22", site_name="", canonical_url="https://example.com/news", meta_debug={}),
    ]
    mock_readability.side_effect = [
        None,
        ContentCandidate(
            extractor_name="readability",
            title="渲染标题",
            content="渲染页正文",
            text_len=5,
            paragraph_count=1,
            link_density=0.1,
            chinese_ratio=1.0,
            noise_hits=[],
        ),
    ]
    mock_trafilatura.side_effect = [None, None]
    mock_rank.side_effect = [
        RankedCandidate(best=None, confidence="low", score=0.0, fallback_needed=True, reasons=["无可用候选"]),
        RankedCandidate(
            best=ContentCandidate(
                extractor_name="readability",
                title="渲染标题",
                content="渲染页正文",
                text_len=5,
                paragraph_count=1,
                link_density=0.1,
                chinese_ratio=1.0,
                noise_hits=[],
            ),
            confidence="medium",
            score=2.0,
            fallback_needed=False,
            reasons=["fallback 成功"],
        ),
    ]
    mock_render.return_value = MagicMock(success=True, final_url="https://example.com/news", html="<html><body><article>渲染页正文</article></body></html>", error_msg="")

    result = crawl_news_url("https://example.com/news")

    assert result.success is True
    assert result.content == "渲染页正文"
    assert result.title == "渲染标题"


@patch("app.core.security.validate_url_for_ssrf", side_effect=lambda url: url)
@patch("app.services.news_crawler.fetch_page")
@patch("app.services.news_crawler.extract_metadata")
@patch("app.services.news_crawler.extract_with_readability")
@patch("app.services.news_crawler.extract_with_trafilatura")
@patch("app.services.news_crawler.rank_candidates")
@patch("app.services.news_crawler.render_page")
def test_crawl_news_url_returns_original_failure_when_render_fallback_disabled(
    mock_render,
    mock_rank,
    mock_trafilatura,
    mock_readability,
    mock_metadata,
    mock_fetch,
    _mock_validate_url,
):
    os.environ["TRUTHCAST_URL_EXTRACT_RENDER_FALLBACK"] = "false"
    mock_fetch.return_value = ("https://example.com/empty", "<html><body>empty</body></html>")
    mock_metadata.return_value = PageMetadata(title="标题", publish_date="", site_name="", canonical_url="https://example.com/empty", meta_debug={})
    mock_readability.return_value = None
    mock_trafilatura.return_value = None
    mock_rank.return_value = RankedCandidate(best=None, confidence="low", score=0.0, fallback_needed=True, reasons=["无可用候选"])

    result = crawl_news_url("https://example.com/empty")

    assert result.success is False
    assert mock_render.called is False


@patch("app.core.security.validate_url_for_ssrf", side_effect=lambda url: url)
@patch("app.services.news_crawler.fetch_page")
@patch("app.services.news_crawler.extract_metadata")
@patch("app.services.news_crawler.extract_with_readability")
@patch("app.services.news_crawler.extract_with_trafilatura")
@patch("app.services.news_crawler.rank_candidates")
@patch("app.services.news_crawler.render_page")
def test_crawl_news_url_keeps_failure_when_rendering_fails(
    mock_render,
    mock_rank,
    mock_trafilatura,
    mock_readability,
    mock_metadata,
    mock_fetch,
    _mock_validate_url,
):
    os.environ["TRUTHCAST_URL_EXTRACT_RENDER_FALLBACK"] = "true"
    mock_fetch.return_value = ("https://example.com/empty", "<html><body>empty</body></html>")
    mock_metadata.return_value = PageMetadata(title="标题", publish_date="", site_name="", canonical_url="https://example.com/empty", meta_debug={})
    mock_readability.return_value = None
    mock_trafilatura.return_value = None
    mock_rank.return_value = RankedCandidate(best=None, confidence="low", score=0.0, fallback_needed=True, reasons=["无可用候选"])
    mock_render.return_value = MagicMock(success=False, final_url="https://example.com/empty", html="", error_msg="browser missing")

    result = crawl_news_url("https://example.com/empty")

    assert result.success is False
    assert "无可用候选" in result.error_msg


@patch("app.core.security.validate_url_for_ssrf", side_effect=lambda url: url)
@patch("app.services.news_crawler.fetch_page")
@patch("app.services.news_crawler.extract_metadata")
@patch("app.services.news_crawler.extract_with_readability")
@patch("app.services.news_crawler.extract_with_trafilatura")
@patch("app.services.news_crawler.rank_candidates")
@patch("app.services.news_crawler.render_page")
def test_crawl_news_url_logs_render_fallback(
    mock_render,
    mock_rank,
    mock_trafilatura,
    mock_readability,
    mock_metadata,
    mock_fetch,
    _mock_validate_url,
):
    os.environ["TRUTHCAST_URL_EXTRACT_RENDER_FALLBACK"] = "true"
    mock_fetch.return_value = ("https://example.com/news", "<html><body>空壳页面</body></html>")
    mock_metadata.side_effect = [
        PageMetadata(title="原始标题", publish_date="", site_name="", canonical_url="https://example.com/news", meta_debug={}),
        PageMetadata(title="渲染标题", publish_date="2026-03-22", site_name="", canonical_url="https://example.com/news", meta_debug={}),
    ]
    mock_readability.side_effect = [
        None,
        ContentCandidate(
            extractor_name="readability",
            title="渲染标题",
            content="渲染页正文",
            text_len=5,
            paragraph_count=1,
            link_density=0.1,
            chinese_ratio=1.0,
            noise_hits=[],
        ),
    ]
    mock_trafilatura.side_effect = [None, None]
    mock_rank.side_effect = [
        RankedCandidate(best=None, confidence="low", score=0.0, fallback_needed=True, reasons=["无可用候选"]),
        RankedCandidate(
            best=ContentCandidate(
                extractor_name="readability",
                title="渲染标题",
                content="渲染页正文",
                text_len=5,
                paragraph_count=1,
                link_density=0.1,
                chinese_ratio=1.0,
                noise_hits=[],
            ),
            confidence="medium",
            score=2.0,
            fallback_needed=False,
            reasons=["fallback 成功"],
        ),
    ]
    mock_render.return_value = MagicMock(success=True, final_url="https://example.com/news", html="<html><body><article>渲染页正文</article></body></html>", error_msg="")

    with patch("app.services.news_crawler.logger.info") as mock_info:
        result = crawl_news_url("https://example.com/news")

    assert result.success is True
    logged = " | ".join(str(call) for call in mock_info.call_args_list)
    assert "触发渲染fallback" in logged
    assert "渲染fallback完成" in logged
