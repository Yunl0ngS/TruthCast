from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path

from fastapi import UploadFile

from app.schemas.multimodal import StoredImageRecord


_METADATA_SUFFIX = ".json"
_FILE_ID_RE = re.compile(r"^img_[a-z0-9]{12}$")
_ALLOWED_MIME_PREFIX = "image/"


def _storage_root() -> Path:
    raw = os.getenv("TRUTHCAST_IMAGE_STORAGE_PATH", "data/uploads").strip()
    path = Path(raw)
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def _metadata_path(file_id: str) -> Path:
    _validate_file_id(file_id)
    return _storage_root() / f"{file_id}{_METADATA_SUFFIX}"


def _blob_path(file_id: str, filename: str) -> Path:
    _validate_file_id(file_id)
    suffix = Path(filename).suffix or ".bin"
    return _storage_root() / f"{file_id}{suffix}"


def _public_url(file_id: str) -> str:
    _validate_file_id(file_id)
    return f"/multimodal/files/{file_id}"


def _validate_file_id(file_id: str) -> None:
    if not _FILE_ID_RE.fullmatch(file_id):
        raise FileNotFoundError(file_id)


def _ensure_within_storage(path: Path) -> Path:
    resolved = path.resolve()
    root = _storage_root()
    if root not in resolved.parents and resolved != root:
        raise FileNotFoundError(resolved.name)
    return resolved


def _validate_upload(file: UploadFile) -> None:
    content_type = (file.content_type or "").strip().lower()
    if not content_type.startswith(_ALLOWED_MIME_PREFIX):
        raise ValueError("only image uploads are supported")


def store_upload(file: UploadFile) -> StoredImageRecord:
    _validate_upload(file)
    file_id = f"img_{uuid.uuid4().hex[:12]}"
    filename = file.filename or f"{file_id}.bin"
    blob_path = _blob_path(file_id, filename)
    content = file.file.read()
    blob_path.write_bytes(content)

    stored = StoredImageRecord(
        file_id=file_id,
        filename=filename,
        mime_type=file.content_type or "application/octet-stream",
        size=len(content),
        local_path=str(blob_path),
        public_url=_public_url(file_id),
    )
    _metadata_path(file_id).write_text(
        json.dumps(stored.model_dump(), ensure_ascii=False), encoding="utf-8"
    )
    return stored


def resolve_stored_image(file_id: str) -> StoredImageRecord:
    metadata_path = _metadata_path(file_id)
    if not metadata_path.exists():
        raise FileNotFoundError(file_id)
    data = json.loads(metadata_path.read_text(encoding="utf-8"))
    stored = StoredImageRecord.model_validate(data)
    if stored.local_path:
        stored = stored.model_copy(
            update={"local_path": str(_ensure_within_storage(Path(stored.local_path)))}
        )
    if not stored.public_url:
        stored = stored.model_copy(update={"public_url": _public_url(file_id)})
    return stored


def delete_stored_image(file_id: str) -> bool:
    stored = resolve_stored_image(file_id)
    removed = False

    if stored.local_path:
        blob_path = Path(stored.local_path)
        if blob_path.exists():
            blob_path.unlink()
            removed = True

    metadata_path = _metadata_path(file_id)
    if metadata_path.exists():
        metadata_path.unlink()
        removed = True

    return removed
