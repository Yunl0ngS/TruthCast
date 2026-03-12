from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.core.logger import get_logger
from app.schemas.export import ExportDataRequest
from app.services.export_service import generate_pdf_bytes, generate_word_bytes

logger = get_logger("truthcast.export")

router = APIRouter(prefix="/export", tags=["export"])


def _filename(ext: str) -> str:
    date_text = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"truthcast-report-{date_text}.{ext}"


@router.post("/pdf")
async def export_pdf(data: ExportDataRequest):
    try:
        content = generate_pdf_bytes(data)
    except RuntimeError as exc:
        logger.error("PDF 导出失败（RuntimeError）: %s", exc)
        raise HTTPException(status_code=500, detail="PDF 导出失败，请稍后重试") from exc
    except Exception as exc:
        logger.error("PDF 导出失败: %s", exc)
        raise HTTPException(status_code=500, detail="PDF 导出失败，请稍后重试") from exc
    filename = _filename("pdf")
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(
        iter([content]), media_type="application/pdf", headers=headers
    )


@router.post("/word")
async def export_word(data: ExportDataRequest):
    try:
        content = generate_word_bytes(data)
    except RuntimeError as exc:
        logger.error("Word 导出失败（RuntimeError）: %s", exc)
        raise HTTPException(
            status_code=500, detail="Word 导出失败，请稍后重试"
        ) from exc
    except Exception as exc:
        logger.error("Word 导出失败: %s", exc)
        raise HTTPException(
            status_code=500, detail="Word 导出失败，请稍后重试"
        ) from exc
    filename = _filename("docx")
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers=headers,
    )
