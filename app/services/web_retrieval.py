import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib import error, parse, request
from urllib.parse import urlparse

from app.core.logger import get_logger
from app.services.evidence_retrieval import domain_weight, freshness_weight, tokenize_text

logger = get_logger("truthcast.web_retrieval")


@dataclass
class WebEvidenceCandidate:
    title: str
    source: str
    url: str
    published_at: str
    summary: str
    relevance: float
    raw_snippet: str
    domain: str
    is_authoritative: bool


def web_retrieval_enabled() -> bool:
    return os.getenv("TRUTHCAST_WEB_RETRIEVAL_ENABLED", "false").strip().lower() == "true"


def search_web_evidence(claim_text: str, top_k: int = 3) -> list[WebEvidenceCandidate]:
    if not web_retrieval_enabled():
        return []

    provider = os.getenv("TRUTHCAST_WEB_SEARCH_PROVIDER", "baidu").strip().lower()
    timeout_sec = float(os.getenv("TRUTHCAST_WEB_RETRIEVAL_TIMEOUT_SEC", "8").strip() or 8)

    try:
        if provider == "serpapi":
            raw_items = _search_serpapi(claim_text, top_k=top_k, timeout_sec=timeout_sec)
        elif provider == "tavily":
            raw_items = _search_tavily(claim_text, top_k=top_k, timeout_sec=timeout_sec)
        elif provider == "searxng":
            raw_items = _search_searxng(claim_text, top_k=top_k, timeout_sec=timeout_sec)
        elif provider == "bocha":
            raw_items = _search_bocha(claim_text, top_k=top_k, timeout_sec=timeout_sec)
        else:
            raw_items = _search_baidu_api(claim_text, top_k=top_k, timeout_sec=timeout_sec)
    except Exception as exc:  # noqa: BLE001
        logger.warning("联网检索失败，error=%s", exc)
        return []

    allowed = _allowed_domains()
    results: list[WebEvidenceCandidate] = []
    claim_tokens = tokenize_text(claim_text)

    for item in raw_items:
        url = str(item.get("url", "")).strip()
        title = str(item.get("title", "")).strip()
        summary = str(item.get("summary", "")).strip()
        if not url or not title:
            continue

        host = _extract_domain(url)
        if allowed and not _in_allowed_domains(host, allowed):
            continue

        published = _normalize_date(str(item.get("published_at", "")).strip())
        overlap = _token_overlap_ratio(claim_tokens, tokenize_text(f"{title} {summary}"))
        provider_score = _safe_float(item.get("score", 0.45), default=0.45)
        relevance = (
            overlap * 0.55
            + provider_score * 0.2
            + domain_weight(url) * 0.15
            + freshness_weight(published) * 0.1
        )
        relevance = round(max(0.0, min(1.0, relevance)), 4)

        results.append(
            WebEvidenceCandidate(
                title=title,
                source=host,
                url=url,
                published_at=published,
                summary=summary,
                relevance=relevance,
                raw_snippet=str(item.get("raw_snippet", summary)).strip(),
                domain=_infer_domain_from_claim(claim_text),
                is_authoritative=domain_weight(url) >= 0.88,
            )
        )

    results.sort(key=lambda row: row.relevance, reverse=True)
    if results:
        logger.info("联网检索完成：query=%s, recalled=%s", claim_text[:80], len(results))
    else:
        logger.info("联网检索未召回可用结果：query=%s", claim_text[:80])
    return results[:top_k]


def infer_web_stance(claim_text: str, evidence: WebEvidenceCandidate) -> str:
    lowered = claim_text.lower()
    combined = f"{evidence.title} {evidence.summary}".lower()
    refute_terms = {"辟谣", "谣言", "misleading", "fact-check", "myth", "misconception"}
    support_terms = {"official", "bulletin", "公告", "通报", "权威", "guidance"}
    risk_terms = {"震惊", "内部消息", "必须转发", "miracle", "must share", "internal source"}

    if any(term in combined for term in refute_terms):
        return "refute"
    if any(term in lowered for term in risk_terms) and any(term in combined for term in refute_terms | support_terms):
        return "refute"
    if evidence.relevance >= 0.5 and any(term in combined for term in support_terms):
        return "support"
    if evidence.relevance < 0.3:
        return "insufficient"
    return "insufficient"


def _search_baidu_api(claim_text: str, top_k: int, timeout_sec: float) -> list[dict[str, Any]]:
    api_key = os.getenv("TRUTHCAST_BAIDU_API_KEY", "").strip()
    if not api_key:
        return []

    endpoint = os.getenv("TRUTHCAST_BAIDU_ENDPOINT", "https://api.qnaigc.com/v1/search/web").strip()
    time_filter = os.getenv("TRUTHCAST_BAIDU_TIME_FILTER", "year").strip() or "year"
    site_filter = [item.strip() for item in os.getenv("TRUTHCAST_BAIDU_SITE_FILTER", "").split(",") if item.strip()]

    payload = {
        "query": claim_text,
        "max_results": max(1, top_k),
        "search_type": "web",
        "time_filter": time_filter,
    }
    if site_filter:
        payload["site_filter"] = site_filter

    body = _post_json(
        endpoint,
        payload,
        timeout_sec,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )

    # qnaigc 常见结构:
    # {"success": true, "data": {"results": [...]}}
    # 也兼容 {"results": [...]} 或 {"data": [...]} 的变体
    results_obj = body.get("results")
    if results_obj is None:
        data_obj = body.get("data")
        if isinstance(data_obj, dict):
            results_obj = data_obj.get("results", [])
        else:
            results_obj = data_obj
    results = results_obj if isinstance(results_obj, list) else []

    normalized: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "title": item.get("title") or item.get("name", ""),
                "url": item.get("url") or item.get("link", ""),
                "summary": item.get("snippet") or item.get("content", ""),
                "score": item.get("score", 0.5),
                "published_at": item.get("published_at") or item.get("date", ""),
                "raw_snippet": item.get("snippet") or item.get("content", ""),
            }
        )
    return normalized


def _search_tavily(claim_text: str, top_k: int, timeout_sec: float) -> list[dict[str, Any]]:
    api_key = os.getenv("TRUTHCAST_TAVILY_API_KEY", "").strip()
    if not api_key:
        return []

    endpoint = os.getenv("TRUTHCAST_TAVILY_ENDPOINT", "https://api.tavily.com/search").strip()
    payload = {
        "api_key": api_key,
        "query": claim_text,
        "max_results": max(1, top_k),
        "search_depth": "basic",
    }
    body = _post_json(endpoint, payload, timeout_sec)

    results = body.get("results", [])
    normalized: list[dict[str, Any]] = []
    for item in results:
        normalized.append(
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "summary": item.get("content", ""),
                "score": item.get("score", 0.4),
                "published_at": item.get("published_date", ""),
                "raw_snippet": item.get("content", ""),
            }
        )
    return normalized


def _search_serpapi(claim_text: str, top_k: int, timeout_sec: float) -> list[dict[str, Any]]:
    api_key = os.getenv("TRUTHCAST_SERPAPI_API_KEY", "").strip()
    if not api_key:
        return []

    endpoint = os.getenv("TRUTHCAST_SERPAPI_ENDPOINT", "https://serpapi.com/search.json").strip()
    query = {
        "q": claim_text,
        "api_key": api_key,
        "engine": "google",
        "num": max(1, top_k),
    }
    url = f"{endpoint}?{parse.urlencode(query)}"
    body = _get_json(url, timeout_sec)

    results = body.get("organic_results", [])
    normalized: list[dict[str, Any]] = []
    for item in results:
        normalized.append(
            {
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "summary": item.get("snippet", ""),
                "score": 0.55,
                "published_at": item.get("date", ""),
                "raw_snippet": item.get("snippet", ""),
            }
        )
    return normalized


def _search_bocha(claim_text: str, top_k: int, timeout_sec: float) -> list[dict[str, Any]]:
    api_key = os.getenv("TRUTHCAST_BOCHA_API_KEY", "").strip()
    if not api_key:
        logger.warning("博查搜索：TRUTHCAST_BOCHA_API_KEY 为空，跳过")
        return []

    endpoint = os.getenv("TRUTHCAST_BOCHA_ENDPOINT", "https://api.bochaai.com/v1/web-search").strip()
    freshness = os.getenv("TRUTHCAST_BOCHA_FRESHNESS", "oneYear").strip()
    summary = os.getenv("TRUTHCAST_BOCHA_SUMMARY", "true").strip().lower() == "true"

    payload = {
        "query": claim_text,
        "count": max(1, min(25, top_k)),
        "summary": summary,
        "freshness": freshness,
    }

    _record_web_trace(
        stage="request",
        method="POST",
        url=endpoint,
        request_headers={"Authorization": "Bearer ***"},
        request_body=payload,
    )

    body = _post_json(
        endpoint,
        payload,
        timeout_sec,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )

    if body.get("code") and body.get("code") != 200:
        logger.warning("博查搜索返回错误：code=%s msg=%s", body.get("code"), body.get("msg"))
        return []

    data = body.get("data", body)
    web_pages = data.get("webPages", {})
    results = web_pages.get("value", [])
    if not isinstance(results, list):
        results = []

    normalized: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "title": item.get("name", "") or item.get("title", ""),
                "url": item.get("url", ""),
                "summary": item.get("summary", "") or item.get("snippet", ""),
                "score": 0.55,
                "published_at": item.get("datePublished", "") or item.get("dateLastCrawled", ""),
                "raw_snippet": item.get("snippet", ""),
            }
        )

    logger.info("博查搜索完成：query=%s, recalled=%s", claim_text[:50], len(normalized))
    return normalized


def _search_searxng(claim_text: str, top_k: int, timeout_sec: float) -> list[dict[str, Any]]:
    endpoint = os.getenv("TRUTHCAST_SEARXNG_ENDPOINT", "https://searx.be/search").strip()
    engines = os.getenv("TRUTHCAST_SEARXNG_ENGINES", "google,bing,duckduckgo").strip()
    categories = os.getenv("TRUTHCAST_SEARXNG_CATEGORIES", "").strip()
    language = os.getenv("TRUTHCAST_SEARXNG_LANGUAGE", "zh-CN").strip()

    params = {
        "q": claim_text,
        "format": "json",
        "engines": engines,
        "language": language,
    }
    if categories:
        params["categories"] = categories

    url = f"{endpoint}?{parse.urlencode(params)}"
    _record_web_trace(
        stage="request",
        method="GET",
        url=url,
        request_headers={},
        request_body=params,
    )

    req = request.Request(url, method="GET")
    try:
        with request.urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read().decode("utf-8")
    except (error.URLError, TimeoutError) as exc:
        _record_web_trace(
            stage="error",
            method="GET",
            url=url,
            request_headers={},
            request_body=params,
            error=str(exc),
        )
        raise RuntimeError(f"SearXNG 请求失败: {exc}") from exc

    body = json.loads(raw)
    _record_web_trace(
        stage="response",
        method="GET",
        url=url,
        request_headers={},
        request_body=params,
        response_body=body,
    )

    results = body.get("results", [])
    normalized: list[dict[str, Any]] = []
    for item in results[:top_k]:
        if not isinstance(item, dict):
            continue
        engine = str(item.get("engine", "unknown")).lower()
        score_map = {"google": 0.55, "bing": 0.50, "duckduckgo": 0.45, "wikipedia": 0.60}
        normalized.append(
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "summary": item.get("content", ""),
                "score": score_map.get(engine, 0.40),
                "published_at": item.get("publishedDate", ""),
                "raw_snippet": item.get("content", ""),
            }
        )
    return normalized


def _post_json(
    url: str,
    payload: dict[str, Any],
    timeout_sec: float,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    final_headers = headers or {"Content-Type": "application/json"}
    _record_web_trace(
        stage="request",
        method="POST",
        url=url,
        request_headers=_safe_headers(final_headers),
        request_body=payload,
    )

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        url,
        data=data,
        headers=final_headers,
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read().decode("utf-8")
    except (error.URLError, TimeoutError) as exc:
        _record_web_trace(
            stage="error",
            method="POST",
            url=url,
            request_headers=_safe_headers(final_headers),
            request_body=payload,
            error=str(exc),
        )
        raise RuntimeError(f"联网检索请求失败: {exc}") from exc

    body = json.loads(raw)
    _record_web_trace(
        stage="response",
        method="POST",
        url=url,
        request_headers=_safe_headers(final_headers),
        request_body=payload,
        response_body=body,
    )
    return body


def _get_json(url: str, timeout_sec: float) -> dict[str, Any]:
    _record_web_trace(
        stage="request",
        method="GET",
        url=url,
        request_headers={},
        request_body={},
    )

    req = request.Request(url, method="GET")
    try:
        with request.urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read().decode("utf-8")
    except (error.URLError, TimeoutError) as exc:
        _record_web_trace(
            stage="error",
            method="GET",
            url=url,
            request_headers={},
            request_body={},
            error=str(exc),
        )
        raise RuntimeError(f"联网检索请求失败: {exc}") from exc

    body = json.loads(raw)
    _record_web_trace(
        stage="response",
        method="GET",
        url=url,
        request_headers={},
        request_body={},
        response_body=body,
    )
    return body


def _allowed_domains() -> set[str]:
    raw = os.getenv("TRUTHCAST_WEB_ALLOWED_DOMAINS", "").strip()
    if not raw:
        return set()
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def _extract_domain(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower().strip()
    if host.startswith("www."):
        return host[4:]
    return host


def _in_allowed_domains(host: str, allowed: set[str]) -> bool:
    for domain in allowed:
        if host == domain or host.endswith(f".{domain}"):
            return True
    return False


def _normalize_date(raw: str) -> str:
    if not raw:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(raw[:19], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _token_overlap_ratio(claim_tokens: set[str], evidence_tokens: set[str]) -> float:
    if not claim_tokens:
        return 0.0
    return len(claim_tokens & evidence_tokens) / len(claim_tokens)


def _infer_domain_from_claim(claim_text: str) -> str:
    lowered = claim_text.lower()
    if any(token in lowered or token in claim_text for token in ("疫苗", "疫情", "infection", "health", "医院")):
        return "health"
    if any(token in lowered or token in claim_text for token in ("公安", "诈骗", "security", "crime")):
        return "security"
    if any(token in lowered or token in claim_text for token in ("网信办", "gov", "政策", "official", "公告")):
        return "governance"
    if any(token in lowered or token in claim_text for token in ("平台", "工信", "ai", "芯片", "technology")):
        return "technology"
    return "general"


def _safe_headers(headers: dict[str, str]) -> dict[str, str]:
    masked: dict[str, str] = {}
    for key, value in headers.items():
        if key.lower() == "authorization":
            masked[key] = "Bearer ***"
        else:
            masked[key] = value
    return masked


def _record_web_trace(
    stage: str,
    method: str,
    url: str,
    request_headers: dict[str, Any],
    request_body: dict[str, Any],
    response_body: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    if os.getenv("TRUTHCAST_DEBUG_WEB_RETRIEVAL", "true").strip().lower() != "true":
        return

    try:
        current_file = os.path.abspath(__file__)
        services_dir = os.path.dirname(current_file)
        app_dir = os.path.dirname(services_dir)
        project_root = os.path.dirname(app_dir)

        debug_dir = os.path.join(project_root, "debug")
        os.makedirs(debug_dir, exist_ok=True)
        trace_file = os.path.join(debug_dir, "web_search_trace.jsonl")

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "method": method,
            "url": url,
            "request_headers": request_headers,
            "request_body": request_body,
            "response_body": response_body,
            "error": error,
        }
        with open(trace_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        if stage == "response":
            logger.info("Web检索响应记录完成：method=%s url=%s", method, url)
        elif stage == "error":
            logger.warning("Web检索错误已记录：method=%s url=%s error=%s", method, url, error)
    except Exception as exc:  # noqa: BLE001
        logger.error("写入 web 检索 trace 失败: %s", exc)
