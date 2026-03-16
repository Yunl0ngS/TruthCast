import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.schemas.multimodal import ImageAnalysisResult, ImageOCRResult


def _fake_extract(image) -> ImageOCRResult:
    return ImageOCRResult(
        file_id=image.file_id,
        source_url=image.public_url,
        ocr_text="原始OCR文本",
        accepted_text="正式入链OCR文本",
        blocks=[],
        confidence=0.92,
        extraction_source="vision_llm",
        status="success",
    )


def _fake_analyze(image, _text) -> ImageAnalysisResult:
    return ImageAnalysisResult(
        file_id=image.file_id,
        source_url=image.public_url,
        image_summary="图片分析摘要",
        relevance_score=80,
        relevance_reason="相关",
        key_elements=[],
        matched_claims=[],
        semantic_conflicts=[],
        image_credibility_label="supportive",
        image_credibility_score=75,
        status="success",
    )


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
    monkeypatch.setattr(
        "app.services.multimodal.orchestrator.extract_image_text", _fake_extract
    )
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
    assert body["image_analyses"] == []
    assert body["claims"] == []
    assert body["report"] is None
    assert body["fusion_report"] is None
    assert body["record_id"] is None


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


def test_multimodal_detect_uses_accepted_ocr_text_in_enhanced_text(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("TRUTHCAST_IMAGE_STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("TRUTHCAST_LLM_ENABLED", "false")
    monkeypatch.setenv("TRUTHCAST_RISK_LLM_ENABLED", "false")

    monkeypatch.setattr(
        "app.services.multimodal.orchestrator.extract_image_text", _fake_extract
    )

    client = TestClient(app)
    upload = client.post(
        "/multimodal/upload",
        files={"file": ("poster.png", b"fake-image-bytes", "image/png")},
    )
    file_id = upload.json()["file_id"]

    response = client.post(
        "/multimodal/detect",
        json={"text": "新闻原文", "images": [{"file_id": file_id}], "force": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert "正式入链OCR文本" in body["enhanced_text"]
    assert "低置信原始OCR" not in body["enhanced_text"]


def test_multimodal_detect_blocks_non_news_before_claims(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_IMAGE_STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("TRUTHCAST_LLM_ENABLED", "false")
    monkeypatch.setenv("TRUTHCAST_RISK_LLM_ENABLED", "false")

    monkeypatch.setattr(
        "app.services.multimodal.orchestrator.extract_image_text", _fake_extract
    )

    def _fake_detect(text: str, force: bool = False, enable_news_gate: bool = False):
        from app.services.text_complexity import ScoreResult
        from app.schemas.detect import StrategyConfig

        assert enable_news_gate is True
        return ScoreResult(
            label="needs_context",
            confidence=0.9,
            score=50,
            reasons=["不是新闻"],
            strategy=StrategyConfig(
                is_news=False,
                news_confidence=0.91,
                detected_text_type="chat",
                news_reason="闲聊文本",
            ),
        )

    def _forbidden_run_claims(*args, **kwargs):
        raise AssertionError("非新闻应在 detect 阶段被拦截，不应进入 claims")

    monkeypatch.setattr(
        "app.services.multimodal.orchestrator.detect_risk_snapshot", _fake_detect
    )
    monkeypatch.setattr(
        "app.services.multimodal.orchestrator.orchestrator.run_claims",
        _forbidden_run_claims,
    )

    client = TestClient(app)
    upload = client.post(
        "/multimodal/upload",
        files={"file": ("poster.png", b"fake-image-bytes", "image/png")},
    )
    file_id = upload.json()["file_id"]

    response = client.post(
        "/multimodal/detect",
        json={"text": "随便聊聊", "images": [{"file_id": file_id}], "force": False},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["detect_data"]["strategy"]["is_news"] is False
    assert body["claims"] == []
    assert body["report"] is None
    assert body["record_id"] is None


def test_multimodal_detect_degrades_when_ocr_providers_unavailable(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("TRUTHCAST_IMAGE_STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("TRUTHCAST_LLM_ENABLED", "false")
    monkeypatch.setenv("TRUTHCAST_RISK_LLM_ENABLED", "false")

    def _failed_extract(_image):
        from app.schemas.multimodal import ImageOCRResult

        return ImageOCRResult(
            file_id="img_x",
            source_url="/multimodal/files/img_x",
            ocr_text="",
            accepted_text="",
            blocks=[],
            confidence=0.0,
            extraction_source="none",
            status="failed",
            error_message="primary=vision unavailable; fallback=paddle unavailable",
        )

    monkeypatch.setattr(
        "app.services.multimodal.orchestrator.extract_image_text", _failed_extract
    )

    client = TestClient(app)
    upload = client.post(
        "/multimodal/upload",
        files={"file": ("poster.png", b"fake-image-bytes", "image/png")},
    )
    file_id = upload.json()["file_id"]

    response = client.post(
        "/multimodal/detect",
        json={"text": "新闻原文", "images": [{"file_id": file_id}], "force": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ocr_results"][0]["status"] == "failed"
    assert body["detect_data"] is not None


def test_multimodal_image_analysis_endpoint_returns_results(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("TRUTHCAST_IMAGE_STORAGE_PATH", str(tmp_path))

    def _fake_analyze_batch(_text, _images):
        return [
            _fake_analyze(
                type(
                    "Img",
                    (),
                    {"file_id": "img_1", "public_url": "/multimodal/files/img_1"},
                )(),
                _text,
            )
        ]

    monkeypatch.setattr(
        "app.api.routes_multimodal.analyze_multimodal_images", _fake_analyze_batch
    )
    client = TestClient(app)

    upload = client.post(
        "/multimodal/upload",
        files={"file": ("poster.png", b"fake-image-bytes", "image/png")},
    )
    file_id = upload.json()["file_id"]

    response = client.post(
        "/multimodal/analyze-images",
        json={"text": "新闻原文", "images": [{"file_id": file_id}]},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["image_analyses"]) == 1
    assert body["image_analyses"][0]["image_summary"] == "图片分析摘要"


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
