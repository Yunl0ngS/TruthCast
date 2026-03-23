import os
from dataclasses import asdict, is_dataclass

from fastapi import APIRouter

from app.core.cache import claims_cache, detect_cache
from app.core.concurrency import llm_slot
from app.core.logger import get_logger
from app.orchestrator import orchestrator
from app.schemas.detect import (
    ClaimsRequest,
    ClaimsResponse,
    DetectRequest,
    DetectResponse,
    EvidenceAlignRequest,
    EvidenceAlignResponse,
    EvidenceRequest,
    EvidenceResponse,
    ReportRequest,
    ReportResponse,
    StrategyConfig,
    UrlCommentItem,
    UrlCrawlResponse,
    UrlDetectRequest,
    UrlDetectResponse,
    UrlRiskDetectRequest,
)
from app.services.history_store import save_report
from app.services.multimodal.fusion import build_report_multimodal_payload
from app.services.pipeline import align_evidences
from app.services.risk_snapshot import detect_risk_snapshot
from app.services.news_crawler import crawl_news_url

router = APIRouter(prefix="/detect", tags=["detect"])
logger = get_logger("truthcast.routes_detect")

_DEFAULT_MAX_CHARS = 8000

# 在模块加载时读取一次，避免每个请求重复调用 os.getenv
try:
    _MAX_INPUT_CHARS: int = int(
        os.getenv("TRUTHCAST_MAX_INPUT_CHARS", _DEFAULT_MAX_CHARS)
    )
except (ValueError, TypeError):
    _MAX_INPUT_CHARS = _DEFAULT_MAX_CHARS


def _normalize_url_comments(comments: object) -> list[UrlCommentItem]:
    normalized: list[UrlCommentItem] = []
    if not isinstance(comments, list):
        return normalized
    for item in comments:
        if isinstance(item, UrlCommentItem):
            normalized.append(item)
        elif is_dataclass(item):
            normalized.append(UrlCommentItem(**asdict(item)))
        elif isinstance(item, dict):
            normalized.append(UrlCommentItem(**item))
    return normalized


def _truncate_text(text: str) -> tuple[str, bool]:
    """若文本超过限制，截断并返回 (truncated_text, was_truncated)"""
    limit = _MAX_INPUT_CHARS
    if len(text) <= limit:
        return text, False
    logger.warning("输入文本超过 %d 字符（实际 %d），已自动截断", limit, len(text))
    return text[:limit], True


@router.post("", response_model=DetectResponse)
def detect_fake_news(payload: DetectRequest) -> DetectResponse:
    text, truncated = _truncate_text(payload.text)

    # 缓存命中，直接返回（截断状态由本次请求决定，无需消耗 LLM 槽位）
    cached = detect_cache.get(text)
    if cached is not None:
        logger.info("风险快照：缓存命中，跳过 LLM 调用")
        return cached.model_copy(update={"truncated": truncated})

    with llm_slot():
        result = detect_risk_snapshot(text, force=payload.force, enable_news_gate=True)
    resp = DetectResponse(
        label=result.label,
        confidence=result.confidence,
        score=result.score,
        reasons=result.reasons,
        strategy=result.strategy,
        truncated=truncated,
    )
    detect_cache.set(text, resp)
    return resp


@router.post("/claims", response_model=ClaimsResponse)
def detect_claims(payload: ClaimsRequest) -> ClaimsResponse:
    text, _ = _truncate_text(payload.text)

    # 缓存命中（仅当未指定自定义策略时缓存，避免策略不同导致误命中）
    if payload.strategy is None:
        cached = claims_cache.get(text)
        if cached is not None:
            logger.info("主张抽取：缓存命中，跳过 LLM 调用")
            return cached

    with llm_slot():
        result = ClaimsResponse(
            claims=orchestrator.run_claims(text, strategy=payload.strategy)
        )

    if payload.strategy is None:
        claims_cache.set(text, result)

    return result


@router.post("/evidence", response_model=EvidenceResponse)
def detect_evidence(payload: EvidenceRequest) -> EvidenceResponse:
    text = payload.text
    if text:
        text, _ = _truncate_text(text)
    with llm_slot():
        evidences = orchestrator.run_evidence(
            text=text, claims=payload.claims, strategy=payload.strategy
        )
    return EvidenceResponse(evidences=evidences)


@router.post("/evidence/align", response_model=EvidenceAlignResponse)
def align_evidence(payload: EvidenceAlignRequest) -> EvidenceAlignResponse:
    """
    证据聚合与对齐

    对每条主张的证据执行：
    1. 证据聚合（多条检索证据 → 少量摘要证据）
    2. 证据对齐（每条摘要证据与主张对齐）
    """
    with llm_slot():
        aligned = align_evidences(
            claims=payload.claims,
            evidences=payload.evidences,
            strategy=payload.strategy,
        )
    return EvidenceAlignResponse(evidences=aligned)


@router.post("/report")
def detect_report(payload: ReportRequest) -> dict:
    text = payload.text
    if text:
        text, _ = _truncate_text(text)

    with llm_slot():
        report = orchestrator.run_report(
            text=text,
            claims=payload.claims,
            evidences=payload.evidences,
            strategy=payload.strategy,
            source_url=payload.source_url,
            source_title=payload.source_title,
            source_publish_date=payload.source_publish_date,
        )
    final_multimodal = build_report_multimodal_payload(
        report=report,
        detect_data=payload.detect_data,
        multimodal=payload.multimodal,
    )
    if final_multimodal is not None:
        report["multimodal"] = final_multimodal
    input_text = (
        text
        or " ".join((item.claim_text for item in (payload.claims or [])))
        or "[无原文]"
    )

    detect_data = None
    if payload.detect_data:
        detect_data = {
            "label": payload.detect_data.label,
            "confidence": payload.detect_data.confidence,
            "score": payload.detect_data.score,
            "reasons": payload.detect_data.reasons,
        }

    record_id = save_report(
        input_text=input_text,
        report=report,
        detect_data=detect_data,
    )

    return {"record_id": record_id, **report}


@router.post("/url", response_model=UrlDetectResponse)
def detect_url(payload: UrlDetectRequest) -> UrlDetectResponse:
    """抓取新闻 URL 并进行初始风险评估（兼容旧接口）"""
    logger.info("链接核查：收到 URL 抓取请求 url=%s", payload.url)
    crawl_resp = crawl_url(payload)
    if not crawl_resp.success:
        return UrlDetectResponse(**crawl_resp.model_dump(), risk=None)
    risk_resp = detect_url_risk(
        UrlRiskDetectRequest(
            url=crawl_resp.url,
            title=crawl_resp.title,
            content=crawl_resp.content,
        )
    )

    return UrlDetectResponse(
        url=crawl_resp.url,
        title=crawl_resp.title,
        content=crawl_resp.content,
        publish_date=crawl_resp.publish_date,
        comments=_normalize_url_comments(crawl_resp.comments),
        risk=risk_resp,
        success=True,
    )


@router.post("/url/crawl", response_model=UrlCrawlResponse)
def crawl_url(payload: UrlDetectRequest) -> UrlCrawlResponse:
    """仅抓取新闻 URL，不等待风险快照。"""
    logger.info("链接核查：收到 URL 抓取请求 url=%s", payload.url)
    crawled = crawl_news_url(payload.url)
    if not crawled.success:
        logger.warning(
            "链接核查：抓取失败 url=%s error=%s",
            payload.url,
            crawled.error_msg,
        )
        return UrlCrawlResponse(
            url=payload.url,
            title="",
            content="",
            publish_date="",
            comments=[],
            success=False,
            error_msg=crawled.error_msg,
        )

    logger.info(
        "链接核查：抓取成功 url=%s title=%s content_len=%s publish_date=%s",
        payload.url,
        (crawled.title or "")[:80],
        len(crawled.content or ""),
        crawled.publish_date or "",
    )
    return UrlCrawlResponse(
        url=payload.url,
        title=crawled.title,
        content=crawled.content,
        publish_date=crawled.publish_date,
        comments=_normalize_url_comments(crawled.comments or []),
        success=True,
    )


@router.post("/url/risk", response_model=DetectResponse)
def detect_url_risk(payload: UrlRiskDetectRequest) -> DetectResponse:
    """对已抓取的新闻文本执行风险快照。"""
    merged_text = f"{payload.title}\n\n{payload.content}".strip()
    with llm_slot():
        risk_result = detect_risk_snapshot(merged_text, enable_news_gate=True)
    logger.info(
        "链接核查：风险快照完成 url=%s score=%s label=%s reason_count=%s",
        payload.url,
        risk_result.score,
        risk_result.label,
        len(risk_result.reasons or []),
    )
    return DetectResponse(
        label=risk_result.label,
        confidence=risk_result.confidence,
        score=risk_result.score,
        reasons=risk_result.reasons,
        strategy=risk_result.strategy,
        truncated=False,
    )
