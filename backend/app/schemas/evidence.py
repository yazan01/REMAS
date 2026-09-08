from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import EvidenceStatus


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    content_type: str
    size_bytes: int
    version: int
    category: str | None = None
    description: str | None = None
    created_at: datetime


class EvidenceLinkIn(BaseModel):
    document_id: str
    question_ids: list[str] = Field(min_length=1)


class EvidenceLinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: str
    question_id: str
    status: str
    reviewer_note: str | None = None
    filename: str | None = None
    created_at: datetime


class EvidenceStatusIn(BaseModel):
    status: EvidenceStatus
    reviewer_note: str | None = None
