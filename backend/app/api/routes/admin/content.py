"""Axes, questions and the maturity scale of a draft version (FR-33).

Every write here goes through `framework_service.assert_editable`, which is the
single place that enforces "a published version is frozen".
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import client_ip, require_ivalue
from app.core.errors import APIError
from app.db.session import get_db
from app.models import Axis, FrameworkVersion, MaturityLevel, Question, User
from app.services import audit, framework_service

router = APIRouter()

# ─────────────────────────── axes & questions ──────────────────────────────


class AxisIn(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    name_ar: str
    name_en: str
    description_ar: str | None = None
    description_en: str | None = None
    weight: float = Field(default=1.0, gt=0)
    order_index: int | None = None


class QuestionIn(BaseModel):
    code: str = Field(min_length=1, max_length=30)
    text_ar: str
    text_en: str
    guidance_ar: str | None = None
    guidance_en: str | None = None
    evidence_hint_ar: str | None = None
    evidence_hint_en: str | None = None
    weight: float = Field(default=1.0, gt=0)
    is_mandatory: bool = True
    evidence_required: bool = False
    allow_not_applicable: bool = True
    criteria: dict[str, Any] | None = None
    order_index: int | None = None


class LevelIn(BaseModel):
    score: int = Field(ge=1, le=10)
    label_ar: str
    label_en: str
    description_ar: str | None = None
    description_en: str | None = None


@router.post("/versions/{version_id}/axes", response_model=dict, status_code=201)
def create_axis(
    version_id: str,
    payload: AxisIn,
    request: Request,
    user: User = Depends(require_ivalue),
    db: Session = Depends(get_db),
) -> dict:
    version = framework_service.assert_editable(framework_service.load_version(db, version_id))
    data = payload.model_dump()
    order = data.pop("order_index") or (len(version.axes) + 1)
    axis = Axis(framework_version_id=version.id, order_index=order, **data)
    db.add(axis)
    db.flush()
    audit.record(db, action="admin.axis_created", entity_type="axis", entity_id=axis.id,
                 actor=user, ip_address=client_ip(request))
    db.commit()
    return {"axis_id": axis.id, "code": axis.code}


@router.patch("/axes/{axis_id}", response_model=dict)
def update_axis(
    axis_id: str,
    payload: dict,
    request: Request,
    user: User = Depends(require_ivalue),
    db: Session = Depends(get_db),
) -> dict:
    axis = db.get(Axis, axis_id)
    if axis is None:
        raise APIError("framework.not_found", status.HTTP_404_NOT_FOUND)
    framework_service.assert_editable(db.get(FrameworkVersion, axis.framework_version_id))
    for field in ("code", "name_ar", "name_en", "description_ar", "description_en",
                  "weight", "order_index"):
        if field in payload:
            setattr(axis, field, payload[field])
    audit.record(db, action="admin.axis_updated", entity_type="axis", entity_id=axis.id,
                 actor=user, payload={"fields": sorted(payload)}, ip_address=client_ip(request))
    db.commit()
    return {"axis_id": axis.id}


@router.delete("/axes/{axis_id}", status_code=204, response_model=None)
def delete_axis(
    axis_id: str,
    request: Request,
    user: User = Depends(require_ivalue),
    db: Session = Depends(get_db),
) -> None:
    axis = db.get(Axis, axis_id)
    if axis is None:
        raise APIError("framework.not_found", status.HTTP_404_NOT_FOUND)
    framework_service.assert_editable(db.get(FrameworkVersion, axis.framework_version_id))
    audit.record(db, action="admin.axis_deleted", entity_type="axis", entity_id=axis.id,
                 actor=user, payload={"code": axis.code}, ip_address=client_ip(request))
    db.delete(axis)
    db.commit()


@router.post("/axes/{axis_id}/questions", response_model=dict, status_code=201)
def create_question(
    axis_id: str,
    payload: QuestionIn,
    request: Request,
    user: User = Depends(require_ivalue),
    db: Session = Depends(get_db),
) -> dict:
    axis = db.get(Axis, axis_id)
    if axis is None:
        raise APIError("framework.not_found", status.HTTP_404_NOT_FOUND)
    framework_service.assert_editable(db.get(FrameworkVersion, axis.framework_version_id))
    data = payload.model_dump()
    order = data.pop("order_index") or (len(axis.questions) + 1)
    question = Question(axis_id=axis.id, order_index=order, **data)
    db.add(question)
    db.flush()
    audit.record(db, action="admin.question_created", entity_type="question",
                 entity_id=question.id, actor=user, ip_address=client_ip(request))
    db.commit()
    return {"question_id": question.id, "code": question.code}


@router.patch("/questions/{question_id}", response_model=dict)
def update_question(
    question_id: str,
    payload: dict,
    request: Request,
    user: User = Depends(require_ivalue),
    db: Session = Depends(get_db),
) -> dict:
    question = db.get(Question, question_id)
    if question is None:
        raise APIError("framework.not_found", status.HTTP_404_NOT_FOUND)
    axis = db.get(Axis, question.axis_id)
    framework_service.assert_editable(db.get(FrameworkVersion, axis.framework_version_id))
    for field in ("code", "text_ar", "text_en", "guidance_ar", "guidance_en",
                  "evidence_hint_ar", "evidence_hint_en", "weight", "is_mandatory",
                  "evidence_required", "allow_not_applicable", "criteria", "order_index"):
        if field in payload:
            setattr(question, field, payload[field])
    audit.record(db, action="admin.question_updated", entity_type="question",
                 entity_id=question.id, actor=user, payload={"fields": sorted(payload)},
                 ip_address=client_ip(request))
    db.commit()
    return {"question_id": question.id}


@router.delete("/questions/{question_id}", status_code=204, response_model=None)
def delete_question(
    question_id: str,
    request: Request,
    user: User = Depends(require_ivalue),
    db: Session = Depends(get_db),
) -> None:
    question = db.get(Question, question_id)
    if question is None:
        raise APIError("framework.not_found", status.HTTP_404_NOT_FOUND)
    axis = db.get(Axis, question.axis_id)
    framework_service.assert_editable(db.get(FrameworkVersion, axis.framework_version_id))
    audit.record(db, action="admin.question_deleted", entity_type="question",
                 entity_id=question.id, actor=user, payload={"code": question.code},
                 ip_address=client_ip(request))
    db.delete(question)
    db.commit()


@router.put("/versions/{version_id}/levels", response_model=list[dict])
def set_levels(
    version_id: str,
    payload: list[LevelIn],
    request: Request,
    user: User = Depends(require_ivalue),
    db: Session = Depends(get_db),
) -> list[dict]:
    version = framework_service.assert_editable(framework_service.load_version(db, version_id))
    for existing in list(version.maturity_levels):
        db.delete(existing)
    db.flush()
    for level in payload:
        db.add(MaturityLevel(framework_version_id=version.id, **level.model_dump()))
    audit.record(db, action="admin.levels_updated", entity_type="framework_version",
                 entity_id=version.id, actor=user, ip_address=client_ip(request))
    db.commit()
    return [{"score": level.score, "label_ar": level.label_ar} for level in payload]
