from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from app.schemas.multimodal import ImageOCRResult, OCRBlock, StoredImageRecord
from app.services.json_utils import serialize_for_json
from app.services.multimodal.providers.ocr.base import OCRProviderSettings
from app.services.multimodal.providers.ocr.paddleocr import extract_with_paddleocr
from app.services.multimodal.providers.ocr.vision_llm import extract_with_vision_llm


def _settings() -> OCRProviderSettings:
    return OCRProviderSettings(
        provider=os.getenv("TRUTHCAST_OCR_PROVIDER", "vision_llm").strip().lower()
        or "vision_llm",
        fallback_provider=os.getenv("TRUTHCAST_OCR_FALLBACK_PROVIDER", "none")
        .strip()
        .lower()
        or "none",
        timeout_sec=float(os.getenv("TRUTHCAST_OCR_TIMEOUT_SEC", "20").strip() or 20),
        max_retries=int(os.getenv("TRUTHCAST_OCR_MAX_RETRIES", "1").strip() or 1),
        retry_delay=float(os.getenv("TRUTHCAST_OCR_RETRY_DELAY", "1").strip() or 1),
        confidence_threshold=float(
            os.getenv("TRUTHCAST_OCR_CONFIDENCE_THRESHOLD", "0.85").strip() or 0.85
        ),
        fallback_threshold=float(
            os.getenv("TRUTHCAST_OCR_FALLBACK_THRESHOLD", "0.7").strip() or 0.7
        ),
        debug_enabled=os.getenv("TRUTHCAST_DEBUG_OCR", "true").strip().lower()
        == "true",
    )


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _record_ocr_trace(stage: str, payload: dict) -> None:
    if not _settings().debug_enabled:
        return
    debug_dir = _project_root() / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    trace_file = debug_dir / "multimodal_ocr_trace.jsonl"
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stage": stage,
        "payload": serialize_for_json(payload),
    }
    with trace_file.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _extract_with_vision_llm(image: StoredImageRecord) -> ImageOCRResult:
    return extract_with_vision_llm(image, timeout_sec=_settings().timeout_sec)


def _extract_with_paddleocr(image: StoredImageRecord) -> ImageOCRResult:
    return extract_with_paddleocr(image, timeout_sec=_settings().timeout_sec)


def _gate_text(result: ImageOCRResult, confidence_threshold: float) -> ImageOCRResult:
    accepted = (
        result.ocr_text.strip() if result.confidence >= confidence_threshold else ""
    )
    gated = result.model_copy(update={"accepted_text": accepted})
    _record_ocr_trace(
        "gate_accept" if accepted else "gate_reject",
        {
            "file_id": result.file_id,
            "confidence": result.confidence,
            "accepted_text": accepted,
            "ocr_text": result.ocr_text,
        },
    )
    return gated


def _normalize_result(
    result: ImageOCRResult | dict, image: StoredImageRecord
) -> ImageOCRResult:
    if isinstance(result, ImageOCRResult):
        return result
    payload = dict(result)
    payload.setdefault("file_id", image.file_id)
    payload.setdefault("source_url", image.public_url)
    payload.setdefault("blocks", [])
    payload.setdefault("confidence", 0.0)
    payload.setdefault("extraction_source", "unknown")
    payload.setdefault("status", "success")
    payload.setdefault("error_message", None)
    payload.setdefault("accepted_text", "")
    return ImageOCRResult.model_validate(payload)


def _call_provider(
    fn: Callable[[StoredImageRecord], ImageOCRResult | dict],
    image: StoredImageRecord,
    retries: int,
    retry_delay: float,
) -> ImageOCRResult:
    last_error: Exception | None = None
    for attempt in range(max(1, retries)):
        try:
            return _normalize_result(fn(image), image)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            _record_ocr_trace(
                "provider_error",
                {
                    "file_id": image.file_id,
                    "provider": getattr(fn, "__name__", "unknown"),
                    "attempt": attempt + 1,
                    "error": str(exc),
                },
            )
            if attempt < max(1, retries) - 1:
                time.sleep(retry_delay)
    if last_error is not None:
        raise last_error
    raise RuntimeError("ocr provider failed without explicit error")


def _failed_result(image: StoredImageRecord, error_message: str) -> ImageOCRResult:
    result = ImageOCRResult(
        file_id=image.file_id,
        source_url=image.public_url,
        ocr_text="",
        accepted_text="",
        blocks=[],
        confidence=0.0,
        extraction_source="none",
        status="failed",
        error_message=error_message,
    )
    _record_ocr_trace(
        "output",
        {
            "file_id": image.file_id,
            "provider": "none",
            "status": result.status,
            "accepted_text": result.accepted_text,
            "confidence": result.confidence,
            "error_message": error_message,
        },
    )
    return result


def extract_image_text(image: StoredImageRecord) -> ImageOCRResult:
    settings = _settings()
    provider_map: dict[str, Callable[[StoredImageRecord], ImageOCRResult]] = {
        "vision_llm": _extract_with_vision_llm,
        "paddleocr": _extract_with_paddleocr,
    }
    provider_name = (
        settings.provider if settings.provider in provider_map else "vision_llm"
    )
    _record_ocr_trace(
        "input",
        {
            "file_id": image.file_id,
            "provider": provider_name,
            "fallback_provider": settings.fallback_provider,
            "timeout_sec": settings.timeout_sec,
            "max_retries": settings.max_retries,
        },
    )
    _record_ocr_trace(
        "provider_selected",
        {"file_id": image.file_id, "provider": provider_name},
    )
    try:
        _record_ocr_trace(
            "provider_request",
            {"file_id": image.file_id, "provider": provider_name},
        )
        result = _call_provider(
            provider_map[provider_name],
            image,
            settings.max_retries,
            settings.retry_delay,
        )
        _record_ocr_trace(
            "provider_response",
            {
                "file_id": image.file_id,
                "provider": result.extraction_source,
                "confidence": result.confidence,
                "status": result.status,
            },
        )
        if (
            result.confidence < settings.fallback_threshold
            and settings.fallback_provider in provider_map
            and settings.fallback_provider != provider_name
        ):
            _record_ocr_trace(
                "fallback_selected",
                {
                    "file_id": image.file_id,
                    "from_provider": provider_name,
                    "to_provider": settings.fallback_provider,
                    "reason": "low_confidence",
                },
            )
            fallback_result = _call_provider(
                provider_map[settings.fallback_provider],
                image,
                settings.max_retries,
                settings.retry_delay,
            )
            result = fallback_result
    except Exception as primary_exc:
        if (
            settings.fallback_provider in provider_map
            and settings.fallback_provider != provider_name
        ):
            _record_ocr_trace(
                "fallback_selected",
                {
                    "file_id": image.file_id,
                    "from_provider": provider_name,
                    "to_provider": settings.fallback_provider,
                    "reason": "provider_error",
                },
            )
            try:
                result = _call_provider(
                    provider_map[settings.fallback_provider],
                    image,
                    settings.max_retries,
                    settings.retry_delay,
                )
            except Exception as fallback_exc:
                return _failed_result(
                    image,
                    f"primary={primary_exc}; fallback={fallback_exc}",
                )
        else:
            return _failed_result(image, str(primary_exc))
    gated = _gate_text(result, settings.confidence_threshold)
    _record_ocr_trace(
        "output",
        {
            "file_id": image.file_id,
            "provider": gated.extraction_source,
            "status": gated.status,
            "accepted_text": gated.accepted_text,
            "confidence": gated.confidence,
        },
    )
    return gated
