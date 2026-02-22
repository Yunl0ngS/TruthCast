from fastapi import APIRouter

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
)
from app.services.history_store import save_report
from app.services.pipeline import align_evidences
from app.services.risk_snapshot import detect_risk_snapshot

router = APIRouter(prefix="/detect", tags=["detect"])


@router.post("", response_model=DetectResponse)
def detect_fake_news(payload: DetectRequest) -> DetectResponse:
    result = detect_risk_snapshot(payload.text)
    return DetectResponse(
        label=result.label,
        confidence=result.confidence,
        score=result.score,
        reasons=result.reasons,
        strategy=result.strategy,
    )


@router.post("/claims", response_model=ClaimsResponse)
def detect_claims(payload: ClaimsRequest) -> ClaimsResponse:
    return ClaimsResponse(claims=orchestrator.run_claims(payload.text, strategy=payload.strategy))


@router.post("/evidence", response_model=EvidenceResponse)
def detect_evidence(payload: EvidenceRequest) -> EvidenceResponse:
    return EvidenceResponse(
        evidences=orchestrator.run_evidence(text=payload.text, claims=payload.claims, strategy=payload.strategy)
    )


@router.post("/evidence/align", response_model=EvidenceAlignResponse)
def align_evidence(payload: EvidenceAlignRequest) -> EvidenceAlignResponse:
    """
    证据聚合与对齐
    
    对每条主张的证据执行：
    1. 证据聚合（多条检索证据 → 少量摘要证据）
    2. 证据对齐（每条摘要证据与主张对齐）
    """
    aligned = align_evidences(
        claims=payload.claims,
        evidences=payload.evidences,
        strategy=payload.strategy,
    )
    return EvidenceAlignResponse(evidences=aligned)


@router.post("/report")
def detect_report(payload: ReportRequest) -> dict:
    report = orchestrator.run_report(
        text=payload.text, claims=payload.claims, evidences=payload.evidences, strategy=payload.strategy
    )
    input_text = payload.text or " ".join((item.claim_text for item in (payload.claims or [])))
    
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
