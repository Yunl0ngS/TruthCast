from __future__ import annotations

from app.schemas.detect import DetectResponse
from app.schemas.multimodal import ImageAnalysisResult, MultimodalFusionReport


def build_fusion_report(
    detect_data: DetectResponse | None, image_analyses: list[ImageAnalysisResult]
) -> MultimodalFusionReport:
    base_score = detect_data.score if detect_data else 50
    has_conflict = any(item.semantic_conflicts for item in image_analyses)
    final_score = min(100, base_score + (12 if has_conflict else 0))
    final_label = detect_data.label if detect_data else "needs_context"
    consistency = "consistent" if not has_conflict else "conflicted"
    conflict_points = [
        conflict for item in image_analyses for conflict in item.semantic_conflicts
    ]
    summary = (
        "已结合图片 OCR 与图片语义结果生成多模态摘要。"
        if image_analyses
        else "当前无可用图片分析结果，沿用文本主链路结论。"
    )
    return MultimodalFusionReport(
        final_risk_score=final_score,
        final_risk_label=final_label,
        multimodal_consistency=consistency,
        conflict_points=conflict_points,
        fusion_summary=summary,
        should_simulate=False,
        image_evidence_status="available" if image_analyses else "unavailable",
    )


def build_report_multimodal_payload(
    report: dict,
    detect_data: DetectResponse | None,
    multimodal: dict | None,
) -> dict | None:
    if not multimodal:
        return None

    raw_text = str(multimodal.get("raw_text", "") or "")
    enhanced_text = str(multimodal.get("enhanced_text", raw_text) or raw_text)
    images = list(multimodal.get("images", []) or [])
    ocr_results = list(multimodal.get("ocr_results", []) or [])
    image_analyses = [
        item
        if isinstance(item, ImageAnalysisResult)
        else ImageAnalysisResult.model_validate(item)
        for item in (multimodal.get("image_analyses", []) or [])
    ]

    fusion = build_fusion_report(detect_data, image_analyses)
    fusion = fusion.model_copy(
        update={
            "fusion_summary": f"{report.get('summary', '')} 已结合图片支路完成最终多模态融合。".strip(),
            "should_simulate": True,
        }
    )
    return {
        "preview_only": False,
        "raw_text": raw_text,
        "enhanced_text": enhanced_text,
        "images": images,
        "ocr_results": ocr_results,
        "image_analyses": [item.model_dump() for item in image_analyses],
        "fusion_report": fusion.model_dump(),
    }
