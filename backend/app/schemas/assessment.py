from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import ServiceLayer


class AssessmentCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    layer: ServiceLayer = ServiceLayer.QUICK_SCORE
    framework_version_id: str | None = None
    selected_axis_ids: list[str] = []


class AssessmentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    layer: str
    status: str
    locked: bool
    created_at: datetime
    submitted_at: datetime | None = None
    framework_version_id: str
    completion: float = 0.0
    overall_score: float | None = None
    maturity_level: int | None = None


class AssessmentDetail(AssessmentSummary):
    selected_axis_ids: list[str] = []
    organization_id: str


class ResponseIn(BaseModel):
    question_id: str
    score: int | None = Field(default=None, ge=1, le=5)
    is_not_applicable: bool = False
    na_rationale: str | None = None
    comment: str | None = None

    @model_validator(mode="after")
    def _check(self) -> "ResponseIn":
        if self.is_not_applicable:
            if not (self.na_rationale or "").strip():
                # BRD FR-09: "Not Applicable" requires a mandatory rationale.
                raise ValueError("na_rationale_required")
            self.score = None
        return self


class ResponseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    question_id: str
    score: int | None = None
    is_not_applicable: bool
    na_rationale: str | None = None
    comment: str | None = None
    override_score: int | None = None
    override_reason: str | None = None
    effective_score: int | None = None
    updated_at: datetime


class OverrideIn(BaseModel):
    score: int | None = Field(default=None, ge=1, le=5)
    reason: str = Field(min_length=3, max_length=500)
    mark_not_applicable: bool = False


class AxisProgress(BaseModel):
    axis_id: str
    code: str
    name_ar: str
    name_en: str
    total_questions: int
    answered_questions: int
    unanswered_mandatory: int
    missing_evidence: int
    completion: float


class ProgressOut(BaseModel):
    assessment_id: str
    status: str
    total_questions: int
    answered_questions: int
    unanswered_mandatory: int
    completion: float
    can_submit: bool
    axes: list[AxisProgress]


class ScoringOut(BaseModel):
    overall_score: float | None = None
    maturity_level: int | None = None
    completeness: float
    evidence_completeness: float
    axes: list[dict[str, Any]]
    strengths: list[str]
    gaps: list[str]
    priorities: list[dict[str, Any]]
    config: dict[str, Any]
    warnings: list[str]
