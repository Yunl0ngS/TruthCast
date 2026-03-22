import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
from app.core.logger import get_logger
from app.services.json_utils import safe_json_loads

logger = get_logger("truthcast.news_crawler")


def _as_float(value: str | None, fallback: float, minimum: float = 0.0) -> float:
    try:
        return max(minimum, float(value or fallback))
    except (TypeError, ValueError):
        return fallback


def _crawler_http_timeout(timeout_sec: float) -> httpx.Timeout:
    return httpx.Timeout(timeout_sec)


def _crawler_llm_timeout() -> httpx.Timeout:
    total_timeout = _as_float(os.getenv("TRUTHCAST_CRAWLER_LLM_TIMEOUT_SEC"), 45.0, minimum=1.0)
    read_timeout = _as_float(
        os.getenv("TRUTHCAST_CRAWLER_LLM_READ_TIMEOUT_SEC"),
        total_timeout,
        minimum=1.0,
    )
    return httpx.Timeout(total_timeout, connect=total_timeout, read=read_timeout, write=total_timeout)


def _crawler_llm_max_retries() -> int:
    try:
        return max(1, int(os.getenv("TRUTHCAST_CRAWLER_LLM_MAX_RETRIES", "2")))
    except (TypeError, ValueError):
        return 2


def _crawler_llm_retry_delay_sec() -> float:
    return _as_float(os.getenv("TRUTHCAST_CRAWLER_LLM_RETRY_DELAY_SEC"), 1.0, minimum=0.0)


@dataclass
class CrawledNews:
    title: str
    content: str
    publish_date: str
    source_url: str
    success: bool = True
    error_msg: str = ""


def crawl_news_url(url: str, timeout_sec: float = 15.0) -> CrawledNews:
    """
    抓取新闻 URL 并提取核心内容 (标题, 正文, 发布日期)
    """
    try:
        logger.info("新闻抓取：开始抓取新闻链接 url=%s", url)
        # SSRF 防护：验证 URL 不指向内部/私有地址
        from app.core.security import SSRFBlockedError, validate_url_for_ssrf

        try:
            url = validate_url_for_ssrf(url)
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

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        with httpx.Client(
            timeout=_crawler_http_timeout(timeout_sec), follow_redirects=True, headers=headers
        ) as client:
            resp = client.get(url)
            resp.raise_for_status()
            html = resp.text
        logger.info(
            "新闻抓取：HTTP获取成功 url=%s status=%s html_len=%s",
            url,
            getattr(resp, "status_code", "unknown"),
            len(html),
        )

        # 1. 简单清洗 HTML 减少 token 消耗
        cleaned_html = _preprocess_html(html)
        logger.info(
            "新闻抓取：HTML预处理完成 url=%s cleaned_len=%s",
            url,
            len(cleaned_html),
        )

        # 2. 调用 LLM 进行结构化提取
        return _extract_news_with_llm(url, cleaned_html)

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


def _preprocess_html(html: str) -> str:
    """
    移除脚本、样式、注释等，只保留主体内容块
    """
    # 移除 script, style, head, nav, footer, iframe
    html = re.sub(
        r"<(script|style|head|nav|footer|iframe)[^>]*>.*?</\1>",
        "",
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    # 移除注释
    html = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)
    # 移除多余空白
    html = re.sub(r"\s+", " ", html).strip()
    # 截断太长的内容，避免正文提取阶段输入过大导致超时
    return html[:10000]


def _extract_news_with_llm(url: str, html: str) -> CrawledNews:
    """
    利用 LLM 从清洗后的 HTML 中提取新闻要素
    """
    api_key = os.getenv("TRUTHCAST_LLM_API_KEY", "").strip()
    if not api_key:
        logger.warning("Crawler: TRUTHCAST_LLM_API_KEY 为空，跳过 LLM 提取")
        return CrawledNews(
            title="",
            content="[未配置 API Key]",
            publish_date="",
            source_url=url,
            success=False,
        )

    base_url = os.getenv("TRUTHCAST_LLM_BASE_URL", "https://api.openai.com/v1").rstrip(
        "/"
    )
    model = os.getenv("TRUTHCAST_CRAWLER_LLM_MODEL") or os.getenv(
        "TRUTHCAST_LLM_MODEL", "gpt-4o-mini"
    )

    system_prompt = """你是一个专业的新闻内容提取助手。你的任务是从给定的 HTML 源码片段中准确提取新闻的核心信息。
请输出合法的 JSON 格式，包含以下字段：
- title: 新闻标题
- content: 新闻正文内容（保持段落完整，移除广告、推荐阅读等干扰信息）
- publish_date: 发布日期（格式：YYYY-MM-DD，如果无法确定则留空）

注意：如果 HTML 中包含多篇新闻或无关信息，请只提取最主要的那篇新闻。
"""
    user_prompt = f"URL: {url}\n\nHTML Snippet:\n{html}"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
    }

    try:
        logger.info("新闻抓取：开始LLM提取 url=%s html_len=%s model=%s", url, len(html), model)
        max_retries = _crawler_llm_max_retries()
        retry_delay_sec = _crawler_llm_retry_delay_sec()
        timeout = _crawler_llm_timeout()
        raw_content = None
        for attempt in range(1, max_retries + 1):
            try:
                with httpx.Client(timeout=timeout) as client:
                    resp = client.post(
                        f"{base_url}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    raw_content = data["choices"][0]["message"]["content"]
                break
            except httpx.ReadTimeout as exc:
                logger.warning(
                    "新闻抓取：LLM提取读取超时 url=%s attempt=%s/%s read_timeout=%ss",
                    url,
                    attempt,
                    max_retries,
                    timeout.read,
                )
                if attempt >= max_retries:
                    raise
                if retry_delay_sec > 0:
                    time.sleep(retry_delay_sec)
            except httpx.TimeoutException:
                logger.warning(
                    "新闻抓取：LLM提取请求超时 url=%s attempt=%s/%s timeout=%ss",
                    url,
                    attempt,
                    max_retries,
                    timeout.connect,
                )
                if attempt >= max_retries:
                    raise
                if retry_delay_sec > 0:
                    time.sleep(retry_delay_sec)
        if raw_content is None:
            raise RuntimeError("LLM extraction returned empty content")

        res_data = safe_json_loads(raw_content)
        title = str(res_data.get("title", "")).strip()
        content = str(res_data.get("content", "")).strip()
        publish_date = str(res_data.get("publish_date", "")).strip()
        logger.info(
            "新闻抓取：提取成功 url=%s title=%s content_len=%s publish_date=%s",
            url,
            title[:80],
            len(content),
            publish_date or "",
        )

        return CrawledNews(
            title=title,
            content=content,
            publish_date=publish_date,
            source_url=url,
            success=True,
        )
    except Exception as exc:
        logger.error("LLM 提取新闻内容失败: %s", exc)
        return CrawledNews(
            title="",
            content="[提取失败]",
            publish_date="",
            source_url=url,
            success=False,
            error_msg=f"LLM extraction failed: {exc}",
        )
