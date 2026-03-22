from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


_DROP_QUERY_KEYS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "spm",
    "from",
    "source",
}


def normalize_monitor_title(title: str) -> str:
    normalized = " ".join(str(title or "").strip().lower().split())
    return normalized


def normalize_monitor_url(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""

    parts = urlsplit(raw)
    filtered_query = urlencode(
        [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() not in _DROP_QUERY_KEYS],
        doseq=True,
    )
    normalized = urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path.rstrip("/"),
            filtered_query,
            "",
        )
    )
    return normalized


def build_monitor_dedupe_key(platform: str, title: str, url: str) -> str:
    normalized_title = normalize_monitor_title(title)
    normalized_url = normalize_monitor_url(url)
    return f"{platform.lower()}::{normalized_title}::{normalized_url}"
