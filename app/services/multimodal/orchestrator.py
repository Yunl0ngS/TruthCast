from __future__ import annotations

from app.orchestrator import orchestrator
from app.schemas.detect import DetectResponse, ReportResponse
from app.schemas.multimodal import (
    ImageInput,
    MultimodalDetectResponse,
    StoredImage,
)
from app.services.multimodal.fusion import build_fusion_report
from app.services.multimodal.image_analysis import analyze_image
from app.services.multimodal.image_storage import resolve_stored_image
from app.services.multimodal.image_text_extraction import extract_image_text
from app.services.risk_snapshot import detect_risk_snapshot


def run_multimodal_detect(
    text: str | None, images: list[ImageInput], force: bool = False
) -> MultimodalDetectResponse:
    raw_text = (text or "").strip()
    stored_images = []
    ocr_results = []
    image_analyses = []

    for image in images:
        if image.file_id:
            stored = resolve_stored_image(image.file_id)
        else:
            continue
        stored_images.append(stored)
        ocr_results.append(extract_image_text(stored))
        image_analyses.append(analyze_image(stored, raw_text))

    ocr_texts = [item.ocr_text.strip() for item in ocr_results if item.ocr_text.strip()]
    enhanced_text = raw_text
    if ocr_texts:
        enhanced_text = "\n\n".join(part for part in [raw_text, *ocr_texts] if part)

    detect_result = detect_risk_snapshot(
        enhanced_text or raw_text or "图片新闻待分析",
        force=force,
        enable_news_gate=False,
    )
    detect_data = DetectResponse(
        label=detect_result.label,
        confidence=detect_result.confidence,
        score=detect_result.score,
        reasons=detect_result.reasons,
        strategy=detect_result.strategy,
        truncated=False,
    )

    claims = orchestrator.run_claims(
        enhanced_text or raw_text or "图片新闻待分析", strategy=detect_result.strategy
    )
    fusion_report = build_fusion_report(detect_data, image_analyses)
    report = ReportResponse(
        risk_score=fusion_report.final_risk_score,
        risk_level=detect_result.strategy.risk_level
        if detect_result.strategy
        else "medium",
        risk_label=fusion_report.final_risk_label,
        detected_scenario="general",
        evidence_domains=[],
        summary=fusion_report.fusion_summary,
        suspicious_points=fusion_report.conflict_points,
        claim_reports=[],
        multimodal={
            "preview_only": True,
            "raw_text": raw_text,
            "enhanced_text": enhanced_text or raw_text,
            "images": [item.model_dump() for item in stored_images],
            "ocr_results": [item.model_dump() for item in ocr_results],
            "image_analyses": [item.model_dump() for item in image_analyses],
            "fusion_report": fusion_report.model_dump(),
        },
    )

    return MultimodalDetectResponse(
        raw_text=raw_text,
        enhanced_text=enhanced_text or raw_text,
        images=[
            StoredImage.model_validate(item.model_dump()) for item in stored_images
        ],
        ocr_results=ocr_results,
        image_analyses=image_analyses,
        detect_data=detect_data,
        claims=claims,
        evidences=[],
        report=report,
        fusion_report=fusion_report,
        record_id=None,
    )
