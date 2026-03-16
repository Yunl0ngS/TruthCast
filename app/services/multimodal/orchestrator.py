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

    for image in images:
        if image.file_id:
            stored = resolve_stored_image(image.file_id)
        else:
            continue
        stored_images.append(stored)
        ocr_results.append(extract_image_text(stored))

    ocr_texts = [
        item.accepted_text.strip() for item in ocr_results if item.accepted_text.strip()
    ]
    enhanced_text = raw_text
    if ocr_texts:
        enhanced_text = "\n\n".join(part for part in [raw_text, *ocr_texts] if part)

    detect_result = detect_risk_snapshot(
        enhanced_text or raw_text or "图片新闻待分析",
        force=force,
        enable_news_gate=True,
    )
    detect_data = DetectResponse(
        label=detect_result.label,
        confidence=detect_result.confidence,
        score=detect_result.score,
        reasons=detect_result.reasons,
        strategy=detect_result.strategy,
        truncated=False,
    )

    return MultimodalDetectResponse(
        raw_text=raw_text,
        enhanced_text=enhanced_text or raw_text,
        images=[
            StoredImage.model_validate(item.model_dump()) for item in stored_images
        ],
        ocr_results=ocr_results,
        image_analyses=[],
        detect_data=detect_data,
        claims=[],
        evidences=[],
        report=None,
        fusion_report=None,
        record_id=None,
    )


def analyze_multimodal_images(
    text: str | None, images: list[ImageInput]
) -> list[ImageAnalysisResult]:
    raw_text = (text or "").strip()
    image_analyses = []
    for image in images:
        if image.file_id:
            stored = resolve_stored_image(image.file_id)
        else:
            continue
        image_analyses.append(analyze_image(stored, raw_text))
    return image_analyses
