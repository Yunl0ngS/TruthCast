import os
from dataclasses import dataclass

import httpx

from app.core.logger import get_logger
from app.services.url_extraction.extractors import (
    ContentCandidate,
    extract_with_readability,
    extract_with_trafilatura,
)
from app.services.url_extraction.llm_postprocess import (
    postprocess_extracted_content,
    rescue_extracted_candidates,
)
from app.services.url_extraction.metadata import extract_metadata
from app.services.url_extraction.rendered import render_page
from app.services.url_extraction.ranker import rank_candidates

logger = get_logger("truthcast.news_crawler")


@dataclass
class CrawledNews:
    title: str
    content: str
    publish_date: str
    source_url: str
    success: bool = True
    error_msg: str = ""


def fetch_page(url: str, timeout_sec: float = 15.0) -> tuple[str, str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }
    with httpx.Client(timeout=httpx.Timeout(timeout_sec), follow_redirects=True, headers=headers) as client:
        response = client.get(url)
        response.raise_for_status()
        final_url = str(response.url)
        html = response.text
    logger.info(
        "新闻抓取：HTTP获取成功 url=%s final_url=%s status=%s html_len=%s",
        url,
        final_url,
        getattr(response, "status_code", "unknown"),
        len(html),
    )
    return final_url, html


def _collect_candidates(html: str) -> list[ContentCandidate]:
    candidates: list[ContentCandidate] = []
    for extractor in (extract_with_readability, extract_with_trafilatura):
        candidate = extractor(html)
        if candidate is None:
            continue
        logger.info(
            "新闻抓取：候选摘要 extractor=%s title=%s text_len=%s paragraphs=%s link_density=%.3f noise_hits=%s",
            candidate.extractor_name,
            candidate.title[:80],
            candidate.text_len,
            candidate.paragraph_count,
            candidate.link_density,
            len(candidate.noise_hits),
        )
        candidates.append(candidate)
    return candidates


def _render_fallback_enabled() -> bool:
    return (os.getenv("TRUTHCAST_URL_EXTRACT_RENDER_FALLBACK", "true") or "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _llm_enhance_enabled() -> bool:
    return (os.getenv("TRUTHCAST_URL_EXTRACT_LLM_ENABLED", "false") or "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def crawl_news_url(url: str, timeout_sec: float = 15.0) -> CrawledNews:
    """
    抓取新闻 URL 并提取核心内容 (标题, 正文, 发布日期)
    """
    try:
        logger.info("新闻抓取：开始抓取新闻链接 url=%s", url)
        from app.core.security import SSRFBlockedError, validate_url_for_ssrf

        try:
            validated_url = validate_url_for_ssrf(url)
        except SSRFBlockedError as exc:
            logger.warning("SSRF 拦截: url=%s, reason=%s", url, exc)
            return CrawledNews(
                title="",
                content="",
                publish_date="",
                source_url=url,
                success=False,
                error_msg=f"URL 安全检查未通过：{exc}",
            )

        final_url, html = fetch_page(validated_url, timeout_sec=timeout_sec)
        logger.info(
            "新闻抓取：HTTP获取成功 url=%s final_url=%s html_len=%s",
            validated_url,
            final_url,
            len(html),
        )
        metadata = extract_metadata(html, final_url)
        logger.info(
            "新闻抓取：metadata提取完成 url=%s title=%s publish_date=%s canonical=%s",
            validated_url,
            metadata.title[:80],
            metadata.publish_date or "",
            metadata.canonical_url or final_url,
        )

        candidates = _collect_candidates(html)
        rescue_candidates: list[ContentCandidate] = list(candidates)
        ranked = rank_candidates(candidates, title_hint=metadata.title)
        logger.info(
            "新闻抓取：候选正文打分完成 url=%s candidate_count=%s confidence=%s score=%.3f fallback_needed=%s",
            validated_url,
            len(candidates),
            ranked.confidence,
            ranked.score,
            ranked.fallback_needed,
        )

        if ranked.best is None and ranked.fallback_needed and _render_fallback_enabled():
            logger.info("新闻抓取：触发渲染fallback url=%s reasons=%s", validated_url, "；".join(ranked.reasons))
            rendered = render_page(metadata.canonical_url or final_url)
            if rendered.success:
                logger.info(
                    "新闻抓取：渲染fallback完成 url=%s final_url=%s html_len=%s",
                    validated_url,
                    rendered.final_url,
                    len(rendered.html),
                )
                rendered_metadata = extract_metadata(rendered.html, rendered.final_url)
                rendered_candidates = _collect_candidates(rendered.html)
                rescue_candidates.extend(rendered_candidates)
                rendered_ranked = rank_candidates(rendered_candidates, title_hint=rendered_metadata.title)
                logger.info(
                    "新闻抓取：渲染fallback打分完成 url=%s candidate_count=%s confidence=%s score=%.3f fallback_needed=%s",
                    validated_url,
                    len(rendered_candidates),
                    rendered_ranked.confidence,
                    rendered_ranked.score,
                    rendered_ranked.fallback_needed,
                )
                if rendered_ranked.best is not None:
                    best = rendered_ranked.best
                    title = rendered_metadata.title or best.title
                    if _llm_enhance_enabled():
                        logger.info("新闻抓取：LLM后处理开始 url=%s source=rendered_fallback", validated_url)
                        enhanced = postprocess_extracted_content(
                            title=title,
                            content=best.content,
                            publish_date=rendered_metadata.publish_date,
                            source_url=rendered_metadata.canonical_url or rendered.final_url,
                        )
                        if enhanced is not None and enhanced.content:
                            logger.info("新闻抓取：LLM后处理成功 url=%s", validated_url)
                            title = enhanced.title or title
                            best = ContentCandidate(
                                extractor_name=best.extractor_name,
                                title=title,
                                content=enhanced.content,
                                text_len=len(enhanced.content),
                                paragraph_count=best.paragraph_count,
                                link_density=best.link_density,
                                chinese_ratio=best.chinese_ratio,
                                noise_hits=best.noise_hits,
                                raw_score=best.raw_score,
                            )
                            publish_date = enhanced.publish_date or rendered_metadata.publish_date
                        else:
                            logger.info("新闻抓取：LLM后处理未生效 url=%s", validated_url)
                            publish_date = rendered_metadata.publish_date
                    else:
                        publish_date = rendered_metadata.publish_date
                    return CrawledNews(
                        title=title,
                        content=best.content,
                        publish_date=publish_date,
                        source_url=rendered_metadata.canonical_url or rendered.final_url,
                        success=True,
                    )
            else:
                logger.warning(
                    "新闻抓取：渲染fallback失败 url=%s error=%s",
                    validated_url,
                    rendered.error_msg,
                )

        if ranked.best is None and _llm_enhance_enabled():
            logger.info("新闻抓取：LLM兜底救援开始 url=%s candidate_count=%s", validated_url, len(rescue_candidates))
            rescued = rescue_extracted_candidates(
                title=metadata.title,
                publish_date=metadata.publish_date,
                source_url=metadata.canonical_url or final_url,
                candidates=rescue_candidates,
            )
            if rescued is not None and rescued.content:
                logger.info("新闻抓取：LLM兜底救援成功 url=%s", validated_url)
                return CrawledNews(
                    title=rescued.title or metadata.title,
                    content=rescued.content,
                    publish_date=rescued.publish_date or metadata.publish_date,
                    source_url=metadata.canonical_url or final_url,
                    success=True,
                )
            logger.info("新闻抓取：LLM兜底救援未生效 url=%s", validated_url)

        if ranked.best is None:
            message = "；".join(ranked.reasons) if ranked.reasons else "无可用候选"
            logger.warning("新闻抓取：未找到可用正文 url=%s reasons=%s", validated_url, message)
            return CrawledNews(
                title=metadata.title,
                content="[提取失败]",
                publish_date=metadata.publish_date,
                source_url=metadata.canonical_url or final_url,
                success=False,
                error_msg=message,
            )

        best = ranked.best
        title = metadata.title or best.title
        publish_date = metadata.publish_date
        if _llm_enhance_enabled():
            logger.info("新闻抓取：LLM后处理开始 url=%s source=primary", validated_url)
            enhanced = postprocess_extracted_content(
                title=title,
                content=best.content,
                publish_date=metadata.publish_date,
                source_url=metadata.canonical_url or final_url,
            )
            if enhanced is not None and enhanced.content:
                logger.info("新闻抓取：LLM后处理成功 url=%s", validated_url)
                title = enhanced.title or title
                best = ContentCandidate(
                    extractor_name=best.extractor_name,
                    title=title,
                    content=enhanced.content,
                    text_len=len(enhanced.content),
                    paragraph_count=best.paragraph_count,
                    link_density=best.link_density,
                    chinese_ratio=best.chinese_ratio,
                    noise_hits=best.noise_hits,
                    raw_score=best.raw_score,
                )
                publish_date = enhanced.publish_date or metadata.publish_date
            else:
                logger.info("新闻抓取：LLM后处理未生效 url=%s", validated_url)
        logger.info(
            "新闻抓取：最终正文选型完成 url=%s extractor=%s title=%s content_len=%s publish_date=%s",
            validated_url,
            best.extractor_name,
            title[:80],
            len(best.content),
            publish_date or "",
        )
        return CrawledNews(
            title=title,
            content=best.content,
            publish_date=publish_date,
            source_url=metadata.canonical_url or final_url,
            success=True,
        )
    except Exception as exc:
        logger.error("抓取 URL 失败: url=%s, error=%s", url, exc)
        return CrawledNews(
            title="",
            content="",
            publish_date="",
            source_url=url,
            success=False,
            error_msg=str(exc),
        )
