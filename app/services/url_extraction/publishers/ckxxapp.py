import html as html_lib
import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from app.services.url_extraction.publishers.common import clean_text


@dataclass
class PublisherComment:
    username: str
    content: str
    publish_time: str

@dataclass
class PublisherArticleResult:
    title: str
    content: str
    publish_date: str
    source_url: str
    comments: list[PublisherComment] = field(default_factory=list)


def _clean_text(value: str | None) -> str:
    return clean_text(value)


def _extract_title(soup: BeautifulSoup) -> str:
    title_node = soup.select_one(".article-title")
    if title_node:
        return _clean_text(title_node.get_text(" ", strip=True))
    og_title = soup.find("meta", attrs={"property": "og:title"})
    if og_title and og_title.get("content"):
        return _clean_text(og_title.get("content"))
    if soup.title and soup.title.string:
        return _clean_text(soup.title.string)
    return ""


def _extract_publish_date(soup: BeautifulSoup) -> str:
    time_node = soup.select_one(".article-time")
    if time_node:
        match = re.search(r"\d{4}-\d{2}-\d{2}", time_node.get_text(" ", strip=True))
        if match:
            return match.group(0)
    published = soup.find("meta", attrs={"property": "article:published_time"})
    if published and published.get("content"):
        match = re.search(r"\d{4}-\d{2}-\d{2}", str(published.get("content")))
        if match:
            return match.group(0)
    return ""


def _extract_content_from_script(html: str) -> str:
    match = re.search(r'var\s+contentTxt\s*=\s*"(?P<content>.*?)";', html, flags=re.DOTALL)
    if not match:
        return ""
    raw = match.group("content")
    raw = (
        raw.replace(r"\/", "/")
        .replace(r"\"", '"')
        .replace(r"\n", "\n")
        .replace(r"\r", "\r")
        .replace(r"\t", "\t")
    )
    raw = html_lib.unescape(raw)
    soup = BeautifulSoup(raw, "html.parser")
    paragraphs = []
    for node in soup.find_all(["p", "div"]):
        text = _clean_text(node.get_text(" ", strip=True))
        if text:
            paragraphs.append(text)
    if not paragraphs:
        text = _clean_text(soup.get_text("\n", strip=True))
        return text
    return "\n\n".join(paragraphs)


def try_extract_ckxxapp_article(source_url: str, html: str) -> PublisherArticleResult | None:
    if not re.match(r"^https?://ckxxapp\.ckxx\.net/pages/\d{4}/\d{2}/\d{2}/.+\.html$", source_url):
        return None
    soup = BeautifulSoup(html or "", "html.parser")
    title = _extract_title(soup)
    content = _extract_content_from_script(html or "")
    if not title or not content:
        return None
    return PublisherArticleResult(
        title=title,
        content=content,
        publish_date=_extract_publish_date(soup),
        source_url=source_url,
        comments=[],
    )
