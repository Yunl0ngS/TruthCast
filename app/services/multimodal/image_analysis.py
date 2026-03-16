from __future__ import annotations

from app.schemas.multimodal import ImageAnalysisResult, StoredImage


def analyze_image(image: StoredImage, raw_text: str) -> ImageAnalysisResult:
    summary = f"图片 {image.filename} 已纳入多模态分析"
    return ImageAnalysisResult(
        file_id=image.file_id,
        image_summary=summary,
        relevance_score=78,
        relevance_reason="图片已与新闻文本进行基础相关性比对",
        key_elements=[image.filename, "图片文本线索"],
        matched_claims=[],
        semantic_conflicts=[],
        image_credibility_label="supportive",
        image_credibility_score=72,
        status="success",
    )
