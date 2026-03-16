from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from app.schemas.detect import ClaimItem, DetectResponse, EvidenceItem, ReportResponse


class ImageInput(BaseModel):
    file_id: str | None = None
    url: str | None = None
    filename: str | None = None

    @model_validator(mode="after")
    def validate_source(self) -> "ImageInput":
        if not (self.file_id or self.url):
            raise ValueError("image input requires file_id or url")
        return self


class StoredImage(BaseModel):
    file_id: str
    filename: str
    mime_type: str
    size: int
    public_url: str | None = None


class StoredImageRecord(StoredImage):
    local_path: str | None = None


class OCRBlock(BaseModel):
    text: str
    confidence: float
    bbox: list[int] | None = None


class ImageOCRResult(BaseModel):
    file_id: str | None = None
    source_url: str | None = None
    ocr_text: str
    blocks: list[OCRBlock] = Field(default_factory=list)
    confidence: float = 0.0
    extraction_source: str = "vision"
    status: str = "success"
    error_message: str | None = None


class ImageAnalysisResult(BaseModel):
    file_id: str | None = None
    source_url: str | None = None
    image_summary: str
    relevance_score: int
    relevance_reason: str
    key_elements: list[str] = Field(default_factory=list)
    matched_claims: list[str] = Field(default_factory=list)
    semantic_conflicts: list[str] = Field(default_factory=list)
    image_credibility_label: str
    image_credibility_score: int
    status: str = "success"
    error_message: str | None = None


class MultimodalFusionReport(BaseModel):
    final_risk_score: int
    final_risk_label: str
    multimodal_consistency: str
    conflict_points: list[str] = Field(default_factory=list)
    fusion_summary: str
    should_simulate: bool = False
    image_evidence_status: str = "available"


class MultimodalDetectRequest(BaseModel):
    text: str | None = None
    images: list[ImageInput] = Field(default_factory=list)
    force: bool = False

    @model_validator(mode="after")
    def validate_payload(self) -> "MultimodalDetectRequest":
        has_text = bool((self.text or "").strip())
        if not has_text and not self.images:
            raise ValueError("multimodal detect requires text or images")
        return self


class MultimodalDetectResponse(BaseModel):
    raw_text: str
    enhanced_text: str
    images: list[StoredImage] = Field(default_factory=list)
    ocr_results: list[ImageOCRResult] = Field(default_factory=list)
    image_analyses: list[ImageAnalysisResult] = Field(default_factory=list)
    detect_data: DetectResponse | None = None
    claims: list[ClaimItem] = Field(default_factory=list)
    evidences: list[EvidenceItem] = Field(default_factory=list)
    report: ReportResponse | None = None
    fusion_report: MultimodalFusionReport | None = None
    record_id: str | None = None
