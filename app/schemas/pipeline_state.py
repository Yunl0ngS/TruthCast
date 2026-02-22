from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


Phase = Literal["detect", "claims", "evidence", "report", "simulation", "content"]
PhaseStatus = Literal["idle", "running", "done", "failed", "canceled"]


class PhaseSnapshot(BaseModel):
    phase: Phase
    status: PhaseStatus
    updated_at: str
    duration_ms: int | None = None
    error_message: str | None = None
    payload: dict[str, Any] | None = None


class PipelineStateUpsertRequest(BaseModel):
    task_id: str
    input_text: str
    phases: dict[Phase, PhaseStatus]
    phase: Phase
    status: PhaseStatus
    duration_ms: int | None = None
    error_message: str | None = None
    payload: dict[str, Any] | None = None
    meta: dict[str, Any] | None = None


class PipelineStateUpsertResponse(BaseModel):
    task_id: str
    phase: Phase
    status: PhaseStatus
    updated_at: str


class PipelineStateLatestResponse(BaseModel):
    task_id: str
    input_text: str
    phases: dict[Phase, PhaseStatus]
    meta: dict[str, Any] = Field(default_factory=dict)
    updated_at: str
    snapshots: list[PhaseSnapshot] = Field(default_factory=list)

