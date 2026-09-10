from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.errors import APIError
from app.db.session import get_db
from app.services import framework_service
from app.models import Axis, Framework, FrameworkVersion, Question, User
from app.models.enums import FrameworkStatus
from app.schemas import AxisOut, FrameworkVersionOut, QuestionOut

router = APIRouter(prefix="/frameworks", tags=["frameworks"])


def _serialise(version: FrameworkVersion, *, with_questions: bool) -> FrameworkVersionOut:
    axes = []
    question_count = 0
    for axis in version.axes:
        question_count += len(axis.questions)
        axes.append(
            AxisOut(
                id=axis.id,
                code=axis.code,
                order_index=axis.order_index,
                name_ar=axis.name_ar,
                name_en=axis.name_en,
                description_ar=axis.description_ar,
                description_en=axis.description_en,
                weight=axis.weight,
                questions=[QuestionOut.model_validate(q) for q in axis.questions]
                if with_questions
                else [],
            )
        )
    return FrameworkVersionOut(
        id=version.id,
        version=version.version,
        status=version.status,
        framework_code=version.framework.code,
        name_ar=version.framework.name_ar,
        name_en=version.framework.name_en,
        description_ar=version.framework.description_ar,
        description_en=version.framework.description_en,
        scoring_config=version.scoring_config,
        maturity_levels=version.maturity_levels,
        axes=axes,
        question_count=question_count,
        axis_count=len(version.axes),
    )


def _load(db: Session, version_id: str) -> FrameworkVersion:
    version = db.get(
        FrameworkVersion,
        version_id,
        options=[
            selectinload(FrameworkVersion.axes).selectinload(Axis.questions),
            selectinload(FrameworkVersion.maturity_levels),
            selectinload(FrameworkVersion.framework),
        ],
    )
    if version is None:
        raise APIError("framework.not_found", status.HTTP_404_NOT_FOUND)
    return version


@router.get("/current", response_model=FrameworkVersionOut)
def get_current(
    with_questions: bool = Query(default=True),
    code: str | None = Query(default=None, description="framework code; defaults to REMAS"),
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FrameworkVersionOut:
    return _serialise(framework_service.current_published_version(db, code), with_questions=with_questions)


@router.get("/versions/{version_id}", response_model=FrameworkVersionOut)
def get_version(
    version_id: str,
    with_questions: bool = Query(default=True),
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FrameworkVersionOut:
    return _serialise(_load(db, version_id), with_questions=with_questions)


@router.get("/versions/{version_id}/axes/{axis_id}/questions", response_model=list[QuestionOut])
def list_axis_questions(
    version_id: str,
    axis_id: str,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Question]:
    axis = db.get(Axis, axis_id)
    if axis is None or axis.framework_version_id != version_id:
        raise APIError("framework.not_found", status.HTTP_404_NOT_FOUND)
    return sorted(axis.questions, key=lambda q: q.order_index)
