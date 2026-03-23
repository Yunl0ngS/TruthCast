import re

import httpx
from bs4 import BeautifulSoup

from app.core.logger import get_logger
from app.services.url_extraction.publishers.ckxxapp import (
    PublisherArticleResult,
    PublisherComment,
)
from app.services.url_extraction.publishers.common import (
    clean_text,
    comments_enabled,
    extract_date_text,
    extract_next_data,
    html_to_paragraph_text,
    max_comment_items,
)

logger = get_logger("truthcast.publisher.thepaper")


def _extract_from_next_data(html: str) -> tuple[str, str, str]:
    data = extract_next_data(html)
    if not data:
        return "", "", ""
    detail = (
        data.get("props", {})
        .get("pageProps", {})
        .get("detailData", {})
        .get("contentDetail", {})
    )
    return (
        clean_text(detail.get("name")),
        html_to_paragraph_text(detail.get("content")),
        extract_date_text(detail.get("pubTime")),
    )


def _fallback_title(soup: BeautifulSoup) -> str:
    title_node = soup.select_one("h1")
    if title_node:
        return clean_text(title_node.get_text(" ", strip=True))
    og_title = soup.find("meta", attrs={"property": "og:title"})
    if og_title and og_title.get("content"):
        return clean_text(og_title.get("content"))
    if soup.title and soup.title.string:
        return clean_text(soup.title.string)
    return ""


def _fallback_publish_date(soup: BeautifulSoup) -> str:
    published = soup.find("meta", attrs={"property": "article:published_time"})
    if published and published.get("content"):
        return extract_date_text(str(published.get("content")))
    return ""


def _extract_article_id(source_url: str, html: str) -> str:
    data = extract_next_data(html)
    cont_id = str(data.get("props", {}).get("pageProps", {}).get("contId", "") or "").strip() if data else ""
    if cont_id:
        return cont_id
    match = re.search(r"newsDetail_forward_(\d+)$", source_url)
    return match.group(1) if match else ""


def _fetch_thepaper_comments(article_id: str) -> list[dict]:
    if not comments_enabled() or not article_id:
        return []
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://www.thepaper.cn/",
        "client-type": "1",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    url = "https://api.thepaper.cn/comment/news/comment/talkList"
    page_size = min(20, max_comment_items())
    page_num = 1
    comments: list[dict] = []
    seen_ids: set[int] = set()
    while len(comments) < max_comment_items():
        payload = {
            "contId": article_id,
            "pageSize": page_size,
            "commentSort": 2,
            "contType": 1,
            "pageNum": page_num,
            "lastId": None,
        }
        response = httpx.post(url, json=payload, headers=headers, timeout=20)
        data = response.json()
        if data.get("code") != 200:
            raise RuntimeError(f"thepaper comment api failed: {data.get('desc') or data.get('code')}")
        rows = data.get("data", {}).get("list", []) or []
        if not rows:
            break
        for row in rows:
            comment_id = int(row.get("commentId", 0) or 0)
            if comment_id and comment_id in seen_ids:
                continue
            if comment_id:
                seen_ids.add(comment_id)
            comments.append(row)
            if len(comments) >= max_comment_items():
                break
        if not data.get("data", {}).get("hasNext"):
            break
        page_num += 1
    return comments[: max_comment_items()]


def _map_thepaper_comments(rows: list[dict]) -> list[PublisherComment]:
    comments: list[PublisherComment] = []
    for row in rows:
        user = row.get("userInfo", {}) or {}
        content = clean_text(row.get("content"))
        if not content:
            continue
        comments.append(
            PublisherComment(
                username=clean_text(user.get("sname")) or clean_text(row.get("userName")) or "匿名用户",
                content=content,
                publish_time=clean_text(row.get("originCreateTime")) or clean_text(row.get("createTime")),
            )
        )
    return comments


def try_extract_thepaper_article(source_url: str, html: str) -> PublisherArticleResult | None:
    if not re.match(r"^https?://www\.thepaper\.cn/newsDetail_forward_\d+$", source_url):
        return None
    soup = BeautifulSoup(html or "", "html.parser")
    title, content, publish_date = _extract_from_next_data(html or "")
    if not title:
        title = _fallback_title(soup)
    if not publish_date:
        publish_date = _fallback_publish_date(soup)
    if not title or not content:
        return None
    comments: list[PublisherComment] = []
    try:
        comments = _map_thepaper_comments(_fetch_thepaper_comments(_extract_article_id(source_url, html or "")))
    except Exception as exc:
        logger.warning("澎湃评论抓取失败 url=%s error=%s", source_url, exc)
    return PublisherArticleResult(
        title=title,
        content=content,
        publish_date=publish_date,
        source_url=source_url,
        comments=comments,
    )
