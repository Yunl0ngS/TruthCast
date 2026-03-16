import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


def test_multimodal_upload_returns_file_metadata(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_IMAGE_STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("TRUTHCAST_LLM_ENABLED", "false")
    monkeypatch.setenv("TRUTHCAST_RISK_LLM_ENABLED", "false")
    client = TestClient(app)

    response = client.post(
        "/multimodal/upload",
        files={"file": ("poster.png", b"fake-image-bytes", "image/png")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["file_id"]
    assert body["filename"] == "poster.png"
    assert body["mime_type"] == "image/png"
    assert body["public_url"] == f"/multimodal/files/{body['file_id']}"
    assert "local_path" not in body

    file_response = client.get(body["public_url"])
    assert file_response.status_code == 200
    assert file_response.content == b"fake-image-bytes"
    assert file_response.headers["content-type"] == "image/png"


def test_multimodal_detect_returns_typed_payload_for_uploaded_image(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("TRUTHCAST_IMAGE_STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("TRUTHCAST_LLM_ENABLED", "false")
    monkeypatch.setenv("TRUTHCAST_RISK_LLM_ENABLED", "false")
    client = TestClient(app)

    upload = client.post(
        "/multimodal/upload",
        files={"file": ("poster.png", b"fake-image-bytes", "image/png")},
    )
    assert upload.status_code == 200
    file_id = upload.json()["file_id"]

    response = client.post(
        "/multimodal/detect",
        json={"text": "新闻原文", "images": [{"file_id": file_id}], "force": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["raw_text"] == "新闻原文"
    assert body["enhanced_text"]
    assert body["images"][0]["file_id"] == file_id
    assert body["ocr_results"]
    assert body["image_analyses"]
    assert body["fusion_report"]


def test_multimodal_detect_rejects_unknown_file_id(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_IMAGE_STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("TRUTHCAST_LLM_ENABLED", "false")
    monkeypatch.setenv("TRUTHCAST_RISK_LLM_ENABLED", "false")
    client = TestClient(app)

    response = client.post(
        "/multimodal/detect",
        json={
            "text": "新闻原文",
            "images": [{"file_id": "img_missing"}],
            "force": True,
        },
    )

    assert response.status_code == 404


def test_multimodal_detect_requires_text_or_images(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_IMAGE_STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("TRUTHCAST_LLM_ENABLED", "false")
    monkeypatch.setenv("TRUTHCAST_RISK_LLM_ENABLED", "false")
    client = TestClient(app)

    response = client.post("/multimodal/detect", json={"text": "", "images": []})

    assert response.status_code == 422


def test_multimodal_delete_removes_uploaded_image(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_IMAGE_STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("TRUTHCAST_LLM_ENABLED", "false")
    monkeypatch.setenv("TRUTHCAST_RISK_LLM_ENABLED", "false")
    client = TestClient(app)

    upload = client.post(
        "/multimodal/upload",
        files={"file": ("poster.png", b"fake-image-bytes", "image/png")},
    )
    assert upload.status_code == 200
    body = upload.json()

    delete_response = client.delete(f"/multimodal/files/{body['file_id']}")
    assert delete_response.status_code == 200
    assert delete_response.json()["deleted"] is True

    file_response = client.get(body["public_url"])
    assert file_response.status_code == 404


def test_multimodal_upload_rejects_non_image_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_IMAGE_STORAGE_PATH", str(tmp_path))
    client = TestClient(app)

    response = client.post(
        "/multimodal/upload",
        files={"file": ("notes.txt", b"not-image", "text/plain")},
    )

    assert response.status_code == 400


def test_multimodal_file_routes_reject_metadata_escape(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_IMAGE_STORAGE_PATH", str(tmp_path))
    client = TestClient(app)

    outside = tmp_path.parent / "outside-secret.txt"
    outside.write_bytes(b"secret")
    metadata = tmp_path / "img_escape.json"
    metadata.write_text(
        json.dumps(
            {
                "file_id": "img_escape",
                "filename": "escape.png",
                "mime_type": "image/png",
                "size": 6,
                "local_path": str(outside),
                "public_url": "/multimodal/files/img_escape",
            }
        ),
        encoding="utf-8",
    )

    get_response = client.get("/multimodal/files/img_escape")
    delete_response = client.delete("/multimodal/files/img_escape")

    assert get_response.status_code == 404
    assert delete_response.status_code == 404
    assert outside.exists()
