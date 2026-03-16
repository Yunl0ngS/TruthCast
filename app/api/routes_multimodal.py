from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import ValidationError

from app.schemas.multimodal import (
    MultimodalDetectRequest,
    MultimodalDetectResponse,
    StoredImage,
)
from app.services.history_store import save_report
from app.services.multimodal import (
    delete_stored_image,
    resolve_stored_image,
    run_multimodal_detect,
    store_upload,
)

router = APIRouter(prefix="/multimodal", tags=["multimodal"])


@router.post("/upload", response_model=StoredImage)
def upload_multimodal_image(file: UploadFile = File(...)) -> StoredImage:
    if not file.filename:
        raise HTTPException(status_code=400, detail="missing filename")
    try:
        return store_upload(file)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/files/{file_id}")
def get_multimodal_image(file_id: str) -> FileResponse:
    try:
        stored = resolve_stored_image(file_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"image not found: {exc}") from exc

    if not stored.local_path:
        raise HTTPException(status_code=404, detail="image path missing")

    return FileResponse(
        path=stored.local_path,
        media_type=stored.mime_type,
        filename=stored.filename,
    )


@router.delete("/files/{file_id}")
def delete_multimodal_image(file_id: str) -> dict[str, bool | str]:
    try:
        deleted = delete_stored_image(file_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"image not found: {exc}") from exc
    return {"file_id": file_id, "deleted": deleted}


@router.post("/detect", response_model=MultimodalDetectResponse)
def detect_multimodal(payload: MultimodalDetectRequest) -> MultimodalDetectResponse:
    try:
        result = run_multimodal_detect(
            text=payload.text,
            images=payload.images,
            force=payload.force,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"image not found: {exc}") from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result.report is not None:
        record_id = save_report(
            input_text=result.raw_text or result.enhanced_text,
            report=result.report.model_dump(),
            detect_data=result.detect_data.model_dump() if result.detect_data else None,
        )
        return result.model_copy(update={"record_id": record_id})
    return result
