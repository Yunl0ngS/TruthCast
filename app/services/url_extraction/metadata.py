import json
import re
from dataclasses import dataclass
from typing import Any

from bs4 import BeautifulSoup
from htmldate import find_date


@dataclass
class PageMetadata:
    title: str
    publish_date: str
    site_name: str
    canonical_url: str
    meta_debug: dict[str, str]


def _clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize_date(value: str | None, html: str) -> str:
    cleaned = _clean_text(value)
    if cleaned:
        match = re.search(r"\d{4}-\d{2}-\d{2}", cleaned)
        if match:
            return match.group(0)
    inferred = _clean_text(find_date(html) or "")
    match = re.search(r"\d{4}-\d{2}-\d{2}", inferred)
    return match.group(0) if match else ""


def _extract_json_ld(soup: BeautifulSoup) -> dict[str, str]:
    payload: dict[str, str] = {}
    for node in soup.find_all("script", attrs={"type": "application/ld+json"}):
        text = node.string or node.get_text() or ""
        text = text.strip()
        if not text:
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        for item in _iter_json_ld_items(data):
            headline = _clean_text(item.get("headline"))
            date_published = _clean_text(item.get("datePublished"))
            if headline and not payload.get("headline"):
                payload["headline"] = headline
            if date_published and not payload.get("datePublished"):
                payload["datePublished"] = date_published
            if payload.get("headline") and payload.get("datePublished"):
                return payload
    return payload


def _iter_json_ld_items(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        items = [data]
        graph = data.get("@graph")
        if isinstance(graph, list):
            items.extend([item for item in graph if isinstance(item, dict)])
        return items
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _get_meta_content(soup: BeautifulSoup, *, prop: str | None = None, name: str | None = None) -> str:
    attrs: dict[str, str] = {}
    if prop:
        attrs["property"] = prop
    if name:
        attrs["name"] = name
    tag = soup.find("meta", attrs=attrs)
    return _clean_text(tag.get("content")) if tag else ""


def extract_metadata(html: str, source_url: str) -> PageMetadata:
    soup = BeautifulSoup(html or "", "html.parser")
    json_ld = _extract_json_ld(soup)

    title = (
        _get_meta_content(soup, prop="og:title")
        or _get_meta_content(soup, name="twitter:title")
        or _clean_text(json_ld.get("headline"))
        or _clean_text(getattr(soup.find("h1"), "get_text", lambda **_: "")(strip=True))
        or _clean_text(getattr(soup.title, "string", ""))
    )
    publish_date = _normalize_date(
        json_ld.get("datePublished")
        or _get_meta_content(soup, prop="article:published_time")
        or _clean_text(getattr(soup.find("time"), "get", lambda *_: "")("datetime"))
        or _clean_text(getattr(soup.find("time"), "get_text", lambda **_: "")(strip=True)),
        html,
    )
    site_name = _get_meta_content(soup, prop="og:site_name")
    canonical_tag = soup.find("link", attrs={"rel": lambda value: value and "canonical" in value})
    canonical_url = _clean_text(canonical_tag.get("href")) if canonical_tag else source_url

    return PageMetadata(
        title=title,
        publish_date=publish_date,
        site_name=site_name,
        canonical_url=canonical_url,
        meta_debug={
            "og_title": _get_meta_content(soup, prop="og:title"),
            "twitter_title": _get_meta_content(soup, name="twitter:title"),
            "json_ld_headline": _clean_text(json_ld.get("headline")),
            "json_ld_date_published": _clean_text(json_ld.get("datePublished")),
        },
    )
