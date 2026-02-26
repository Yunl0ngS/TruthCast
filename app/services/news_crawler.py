import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
from app.core.logger import get_logger
from app.services.json_utils import safe_json_loads

logger = get_logger("truthcast.news_crawler")

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
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        with httpx.Client(timeout=timeout_sec, follow_redirects=True, headers=headers) as client:
            resp = client.get(url)
            resp.raise_for_status()
            html = resp.text
            
        # 1. 简单清洗 HTML 减少 token 消耗
        cleaned_html = _preprocess_html(html)
        
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
            error_msg=str(exc)
        )

def _preprocess_html(html: str) -> str:
    """
    移除脚本、样式、注释等，只保留主体内容块
    """
    # 移除 script, style, head, nav, footer, iframe
    html = re.sub(r"<(script|style|head|nav|footer|iframe)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # 移除注释
    html = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)
    # 移除多余空白
    html = re.sub(r"\s+", " ", html).strip()
    # 截断太长的内容 (例如保留前 15000 字符，通常够了)
    return html[:15000]

def _extract_news_with_llm(url: str, html: str) -> CrawledNews:
    """
    利用 LLM 从清洗后的 HTML 中提取新闻要素
    """
    api_key = os.getenv("TRUTHCAST_LLM_API_KEY", "").strip()
    if not api_key:
        logger.warning("Crawler: TRUTHCAST_LLM_API_KEY 为空，跳过 LLM 提取")
        return CrawledNews(title="", content="[未配置 API Key]", publish_date="", source_url=url, success=False)

    base_url = os.getenv("TRUTHCAST_LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.getenv("TRUTHCAST_CRAWLER_LLM_MODEL") or os.getenv("TRUTHCAST_LLM_MODEL", "gpt-4o-mini")
    
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
            {"role": "user", "content": user_prompt}
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1
    }
    
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(f"{base_url}/chat/completions", 
                               headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                               json=payload)
            resp.raise_for_status()
            data = resp.json()
            raw_content = data["choices"][0]["message"]["content"]
            
        res_data = safe_json_loads(raw_content)
        
        return CrawledNews(
            title=str(res_data.get("title", "")).strip(),
            content=str(res_data.get("content", "")).strip(),
            publish_date=str(res_data.get("publish_date", "")).strip(),
            source_url=url,
            success=True
        )
    except Exception as exc:
        logger.error("LLM 提取新闻内容失败: %s", exc)
        return CrawledNews(
            title="",
            content="[提取失败]",
            publish_date="",
            source_url=url,
            success=False,
            error_msg=f"LLM extraction failed: {exc}"
        )
