import re

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from app.core.logger import get_logger
from app.services.url_extraction.publishers.ckxxapp import (
    PublisherArticleResult,
    PublisherComment,
)
from app.services.url_extraction.publishers.common import (
    clean_text,
    comments_enabled,
    extract_date_from_unix,
    extract_date_text,
    extract_next_data,
    format_datetime_from_unix,
    html_to_paragraph_text,
    max_comment_items,
)

logger = get_logger("truthcast.publisher.cls")


def _extract_from_next_data(html: str) -> tuple[str, str, str]:
    data = extract_next_data(html)
    if not data:
        return "", "", ""
    detail = (
        data.get("props", {})
        .get("initialState", {})
        .get("detail", {})
        .get("articleDetail", {})
    )
    if not detail:
        return "", "", ""
    publish_date = (
        extract_date_from_unix(detail.get("ctime"))
        or extract_date_text(detail.get("publish_time"))
        or extract_date_text(detail.get("create_time"))
    )
    return (
        clean_text(detail.get("title")),
        html_to_paragraph_text(detail.get("content")),
        publish_date,
    )


def _fallback_title(soup: BeautifulSoup) -> str:
    title_node = soup.select_one(".detail-title")
    if title_node:
        return clean_text(title_node.get_text(" ", strip=True))
    if soup.title and soup.title.string:
        return clean_text(soup.title.string)
    return ""


def _fallback_content(soup: BeautifulSoup) -> str:
    content_node = soup.select_one(".detail-content")
    if not content_node:
        return ""
    return html_to_paragraph_text(str(content_node))


def _fallback_publish_date(soup: BeautifulSoup) -> str:
    published = soup.find("meta", attrs={"property": "article:published_time"})
    if published and published.get("content"):
        return extract_date_text(str(published.get("content")))
    return ""


def _extract_article_id(source_url: str, html: str) -> str:
    data = extract_next_data(html)
    article_id = (
        str(
            data.get("props", {})
            .get("initialState", {})
            .get("detail", {})
            .get("articleDetail", {})
            .get("id", "")
            or ""
        ).strip()
        if data
        else ""
    )
    if article_id:
        return article_id
    match = re.search(r"/detail/(\d+)$", source_url)
    return match.group(1) if match else ""


def _fetch_cls_comments(source_url: str) -> list[dict]:
    if not comments_enabled():
        return []
    captured: list[dict] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1400, "height": 1000})

            def on_response(response) -> None:
                if "/v2/comment/get_list" not in response.url:
                    return
                try:
                    payload = response.json()
                except Exception:
                    return
                data = payload.get("data", {}) or {}
                captured.extend(data.get("top", []) or [])
                captured.extend(data.get("list", []) or [])

            page.on("response", on_response)
            page.goto(source_url, wait_until="networkidle", timeout=20000)
            page.wait_for_timeout(3000)
        finally:
            browser.close()
    return captured[: max_comment_items()]


def _map_cls_comments(rows: list[dict]) -> list[PublisherComment]:
    comments: list[PublisherComment] = []
    for row in rows:
        content = clean_text(row.get("content"))
        if not content:
            continue
        comments.append(
            PublisherComment(
                username=clean_text(row.get("name")) or "匿名用户",
                content=content,
                publish_time=format_datetime_from_unix(row.get("time")),
            )
        )
    return comments


def try_extract_cls_article(source_url: str, html: str) -> PublisherArticleResult | None:
    if not re.match(r"^https?://www\.cls\.cn/detail/\d+$", source_url):
        return None
    soup = BeautifulSoup(html or "", "html.parser")
    title, content, publish_date = _extract_from_next_data(html or "")
    if not title:
        title = _fallback_title(soup)
    if not content:
        content = _fallback_content(soup)
    if not publish_date:
        publish_date = _fallback_publish_date(soup)
    if not title or not content:
        return None
    comments: list[PublisherComment] = []
    try:
        article_id = _extract_article_id(source_url, html or "")
        if article_id:
            comments = _map_cls_comments(_fetch_cls_comments(source_url))
    except Exception as exc:
        logger.warning("财联社评论抓取失败 url=%s error=%s", source_url, exc)
    return PublisherArticleResult(
        title=title,
        content=content,
        publish_date=publish_date,
        source_url=source_url,
        comments=comments,
    )
