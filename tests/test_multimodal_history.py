from fastapi.testclient import TestClient

from app.main import app
from app.schemas.detect import ClaimItem, EvidenceItem
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


def test_multimodal_history_detail_returns_fusion_and_image_metadata(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("TRUTHCAST_IMAGE_STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("TRUTHCAST_LLM_ENABLED", "false")
    monkeypatch.setenv("TRUTHCAST_RISK_LLM_ENABLED", "false")
    monkeypatch.setattr(
        "app.services.multimodal.orchestrator.extract_image_text", _fake_extract
    )
    monkeypatch.setattr(
        "app.api.routes_multimodal.analyze_multimodal_images",
        lambda text, images: [
            _fake_analyze(
                type(
                    "Img",
                    (),
                    {"file_id": images[0].file_id, "public_url": "/multimodal/files/x"},
                )(),
                text,
            )
        ],
    )
    client = TestClient(app)

    upload = client.post(
        "/multimodal/upload",
        files={"file": ("poster.png", b"fake-image-bytes", "image/png")},
    )
    assert upload.status_code == 200
    file_id = upload.json()["file_id"]

    detect = client.post(
        "/multimodal/detect",
        json={"text": "新闻原文", "images": [{"file_id": file_id}], "force": True},
    )
    assert detect.status_code == 200
    detect_body = detect.json()

    analysis = client.post(
        "/multimodal/analyze-images",
        json={"text": "新闻原文", "images": [{"file_id": file_id}]},
    )
    assert analysis.status_code == 200

    report = client.post(
        "/detect/report",
        json={
            "text": detect_body["enhanced_text"],
            "claims": [
                {
                    "claim_id": "c1",
                    "claim_text": "示例主张",
                    "source_sentence": "示例主张",
                }
            ],
            "evidences": [
                {
                    "evidence_id": "e1",
                    "claim_id": "c1",
                    "title": "证据标题",
                    "source": "来源",
                    "url": "https://example.com",
                    "published_at": "2026-03-16",
                    "summary": "证据摘要",
                    "stance": "support",
                    "source_weight": 0.8,
                }
            ],
            "detect_data": detect_body["detect_data"],
            "strategy": detect_body["detect_data"]["strategy"],
            "multimodal": {
                "raw_text": detect_body["raw_text"],
                "enhanced_text": detect_body["enhanced_text"],
                "images": detect_body["images"],
                "ocr_results": detect_body["ocr_results"],
                "image_analyses": analysis.json()["image_analyses"],
            },
        },
    )
    assert report.status_code == 200
    body = report.json()
    assert body["record_id"]

    detail = client.get(f"/history/{body['record_id']}")
    assert detail.status_code == 200
    history = detail.json()

    assert history["report"]["multimodal"]
    multimodal = history["report"]["multimodal"]
    assert multimodal["raw_text"] == "新闻原文"
    assert multimodal["images"][0]["file_id"] == file_id
    assert multimodal["fusion_report"]["fusion_summary"]
    assert multimodal["preview_only"] is False
