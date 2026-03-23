import json
import os
import re
from datetime import datetime, timedelta, timezone

from bs4 import BeautifulSoup


def clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def extract_next_data(html: str) -> dict | None:
    match = re.search(
        r'<script id="__NEXT_DATA__"[^>]*>(?P<data>.*?)</script>',
        html or "",
        flags=re.DOTALL,
    )
    if not match:
        return None
    try:
        return json.loads(match.group("data"))
    except json.JSONDecodeError:
        return None


def html_to_paragraph_text(raw_html: str | None) -> str:
    soup = BeautifulSoup(raw_html or "", "html.parser")
    paragraphs: list[str] = []
    nodes = soup.find_all("p")
    if not nodes:
        nodes = soup.find_all("div")
    for node in nodes:
        text = clean_text(node.get_text(" ", strip=True))
        if text:
            paragraphs.append(text)
    if not paragraphs:
        return clean_text(soup.get_text("\n", strip=True))
    return "\n\n".join(paragraphs)


def extract_date_text(value: str | None) -> str:
    match = re.search(r"\d{4}-\d{2}-\d{2}", str(value or ""))
    return match.group(0) if match else ""


def extract_date_from_unix(value: int | float | None) -> str:
    if value is None:
        return ""
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return ""
    if timestamp > 10_000_000_000:
        timestamp /= 1000.0
    try:
        china_tz = timezone(timedelta(hours=8))
        return datetime.fromtimestamp(timestamp, tz=china_tz).strftime("%Y-%m-%d")
    except (OverflowError, OSError, ValueError):
        return ""


def format_datetime_from_unix(value: int | float | None) -> str:
    if value is None:
        return ""
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return ""
    if timestamp > 10_000_000_000:
        timestamp /= 1000.0
    try:
        china_tz = timezone(timedelta(hours=8))
        return datetime.fromtimestamp(timestamp, tz=china_tz).strftime("%Y-%m-%d %H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return ""


def comments_enabled() -> bool:
    value = (os.getenv("TRUTHCAST_URL_COMMENT_ENABLED", "true") or "true").strip().lower()
    return value in {"1", "true", "yes", "on"}


def max_comment_items() -> int:
    try:
        return max(1, int(os.getenv("TRUTHCAST_URL_COMMENT_MAX_ITEMS", "100")))
    except (TypeError, ValueError):
        return 100
