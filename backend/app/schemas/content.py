from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

# Every content object carries both languages. The client toggles instantly
# without a round-trip, and the stored answer is never tied to one language.


class MaturityLevelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    score: int
    label_ar: str
    label_en: str
    description_ar: str | None = None
    description_en: str | None = None


class QuestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    code: str
    order_index: int
    text_ar: str
    text_en: str
    guidance_ar: str | None = None
    guidance_en: str | None = None
    evidence_hint_ar: str | None = None
    evidence_hint_en: str | None = None
    weight: float
    is_mandatory: bool
    evidence_required: bool
    allow_not_applicable: bool
    response_type: str
    criteria: dict[str, Any] | None = None


class AxisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    code: str
    order_index: int
    name_ar: str
    name_en: str
    description_ar: str | None = None
    description_en: str | None = None
    weight: float
    questions: list[QuestionOut] = []


class FrameworkVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    version: str
    status: str
    framework_code: str
    name_ar: str
    name_en: str
    description_ar: str | None = None
    description_en: str | None = None
    scoring_config: dict[str, Any]
    maturity_levels: list[MaturityLevelOut] = []
    axes: list[AxisOut] = []
    question_count: int = 0
    axis_count: int = 0


class LayerOut(BaseModel):
    """The service catalogue rendered on the landing screen (BRD FR-01)."""

    key: str
    name_ar: str
    name_en: str
    summary_ar: str
    summary_en: str
    includes_ar: list[str]
    includes_en: list[str]
    output_ar: str
    output_en: str
