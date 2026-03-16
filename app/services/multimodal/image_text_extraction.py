from __future__ import annotations

from app.schemas.multimodal import ImageOCRResult, OCRBlock, StoredImage


def extract_image_text(image: StoredImage) -> ImageOCRResult:
    text = f"图片提字：{image.filename}"
    return ImageOCRResult(
        file_id=image.file_id,
        ocr_text=text,
        blocks=[OCRBlock(text=text, confidence=0.96)],
        confidence=0.96,
        extraction_source="stub_vision",
        status="success",
    )
