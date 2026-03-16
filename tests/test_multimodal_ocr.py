from pathlib import Path

import json

import pytest

from app.schemas.multimodal import StoredImageRecord
from app.services.multimodal import image_text_extraction as ocr_service


def _stored_image(tmp_path: Path) -> StoredImageRecord:
    image_path = tmp_path / "poster.png"
    image_path.write_bytes(b"fake-image-bytes")
    return StoredImageRecord(
        file_id="img_123456abcdef",
        filename="poster.png",
        mime_type="image/png",
        size=len(b"fake-image-bytes"),
        public_url="/multimodal/files/img_123456abcdef",
        local_path=str(image_path),
    )


def test_extract_image_text_uses_vision_llm_provider_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TRUTHCAST_OCR_PROVIDER", raising=False)
    monkeypatch.setenv("TRUTHCAST_OCR_FALLBACK_PROVIDER", "none")
    monkeypatch.setenv("TRUTHCAST_OCR_MAX_RETRIES", "1")
    called: list[str] = []

    def fake_vision(image: StoredImageRecord):
        called.append(image.file_id)
        raise RuntimeError("vision provider not wired")

    monkeypatch.setattr(
        ocr_service, "_extract_with_vision_llm", fake_vision, raising=False
    )

    result = ocr_service.extract_image_text(_stored_image(tmp_path))

    assert called == ["img_123456abcdef"]
    assert result.status == "failed"
    assert result.ocr_text == ""
    assert "vision provider not wired" in (result.error_message or "")


def test_extract_image_text_falls_back_to_paddleocr_when_primary_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRUTHCAST_OCR_PROVIDER", "vision_llm")
    monkeypatch.setenv("TRUTHCAST_OCR_FALLBACK_PROVIDER", "paddleocr")

    def fake_vision(_: StoredImageRecord):
        raise RuntimeError("vision failed")

    def fake_paddle(_: StoredImageRecord):
        return {
            "ocr_text": "候选 provider 提字结果",
            "blocks": [{"text": "候选 provider 提字结果", "confidence": 0.95}],
            "confidence": 0.95,
            "extraction_source": "paddleocr",
            "status": "success",
            "error_message": None,
        }

    monkeypatch.setattr(
        ocr_service, "_extract_with_vision_llm", fake_vision, raising=False
    )
    monkeypatch.setattr(
        ocr_service, "_extract_with_paddleocr", fake_paddle, raising=False
    )

    result = ocr_service.extract_image_text(_stored_image(tmp_path))

    assert result.ocr_text == "候选 provider 提字结果"
    assert result.extraction_source == "paddleocr"


def test_extract_image_text_rejects_low_confidence_text_from_enhanced_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRUTHCAST_OCR_PROVIDER", "vision_llm")
    monkeypatch.setenv("TRUTHCAST_OCR_CONFIDENCE_THRESHOLD", "0.85")

    def fake_vision(_: StoredImageRecord):
        return {
            "ocr_text": "低置信文本",
            "blocks": [{"text": "低置信文本", "confidence": 0.52}],
            "confidence": 0.52,
            "extraction_source": "vision_llm",
            "status": "success",
            "error_message": None,
        }

    monkeypatch.setattr(
        ocr_service, "_extract_with_vision_llm", fake_vision, raising=False
    )

    result = ocr_service.extract_image_text(_stored_image(tmp_path))

    assert result.ocr_text == "低置信文本"
    assert getattr(result, "accepted_text", "") == ""


def test_extract_image_text_writes_ocr_trace_when_debug_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRUTHCAST_OCR_PROVIDER", "vision_llm")
    monkeypatch.setenv("TRUTHCAST_DEBUG_OCR", "true")
    monkeypatch.setattr(ocr_service, "_project_root", lambda: tmp_path, raising=False)

    def fake_vision(_: StoredImageRecord):
        return {
            "ocr_text": "可接受文本",
            "blocks": [{"text": "可接受文本", "confidence": 0.91}],
            "confidence": 0.91,
            "extraction_source": "vision_llm",
            "status": "success",
            "error_message": None,
        }

    monkeypatch.setattr(
        ocr_service, "_extract_with_vision_llm", fake_vision, raising=False
    )

    ocr_service.extract_image_text(_stored_image(tmp_path))

    trace_file = tmp_path / "debug" / "multimodal_ocr_trace.jsonl"
    assert trace_file.exists()
    stages = [
        json.loads(line)["stage"]
        for line in trace_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert "provider_selected" in stages
    assert "gate_accept" in stages
    assert "output" in stages


def test_extract_image_text_degrades_to_failed_result_when_all_providers_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRUTHCAST_OCR_PROVIDER", "vision_llm")
    monkeypatch.setenv("TRUTHCAST_OCR_FALLBACK_PROVIDER", "paddleocr")
    monkeypatch.setenv("TRUTHCAST_OCR_MAX_RETRIES", "1")

    def fake_vision(_: StoredImageRecord):
        raise RuntimeError("vision unavailable")

    def fake_paddle(_: StoredImageRecord):
        raise RuntimeError("paddle unavailable")

    monkeypatch.setattr(
        ocr_service, "_extract_with_vision_llm", fake_vision, raising=False
    )
    monkeypatch.setattr(
        ocr_service, "_extract_with_paddleocr", fake_paddle, raising=False
    )

    result = ocr_service.extract_image_text(_stored_image(tmp_path))

    assert result.status == "failed"
    assert result.ocr_text == ""
    assert result.accepted_text == ""
    assert "paddle unavailable" in (result.error_message or "")
