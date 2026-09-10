"""Question assignment, deadlines and overdue tracking — BRD FR-12.

Assignment is what turns a questionnaire into work someone owns: each question
can be handed to a named member with a due date, and progress is reported per
user rather than only per assessment, so a manager can see who is behind before
the deadline rather than after it.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import can_manage_org, client_ip, get_assessment, get_current_user
from app.core.errors import APIError
from app.core.security import utcnow
from app.db.session import get_db
from app.models import (
    Assessment,
    Response as ResponseRow,
    User,
)
from app.models.enums import IVALUE_ROLES
from app.services import assessment_service, audit

router = APIRouter(tags=["governance"])



class AssignIn(BaseModel):
    question_ids: list[str] = Field(min_length=1)
    assigned_to_id: str | None = None
    due_at: datetime | None = None


class AssessmentDueIn(BaseModel):
    due_at: datetime | None = None


@router.put("/assessments/{assessment_id}/assignments", response_model=dict)
def assign_questions(
    payload: AssignIn,
    request: Request,
    assessment: Assessment = Depends(get_assessment),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Assign questions to a team member with an optional deadline.

    A response row is created if the question has not been touched yet, so the
    assignment survives even before anybody answers.
    """
    if not can_manage_org(user):
        raise APIError("auth.forbidden", status.HTTP_403_FORBIDDEN)

    allowed = {
        q.id
        for axis in assessment_service.selected_axes(db, assessment)
        for q in axis.questions
    }
    if payload.assigned_to_id:
        target = db.get(User, payload.assigned_to_id)
        if target is None or (
            target.organization_id != assessment.organization_id
            and target.role not in IVALUE_ROLES
        ):
            raise APIError("auth.forbidden", status.HTTP_403_FORBIDDEN)

    existing = {
        r.question_id: r
        for r in db.scalars(
            select(ResponseRow).where(ResponseRow.assessment_id == assessment.id)
        )
    }

    touched = 0
    for question_id in payload.question_ids:
        if question_id not in allowed:
            raise APIError("question.not_in_assessment", status.HTTP_400_BAD_REQUEST)
        response = existing.get(question_id)
        if response is None:
            response = ResponseRow(assessment_id=assessment.id, question_id=question_id)
            db.add(response)
            existing[question_id] = response
        response.assigned_to_id = payload.assigned_to_id
        response.assigned_by_id = user.id
        response.assigned_at = utcnow()
        response.due_at = payload.due_at
        touched += 1

    audit.record(
        db, action="assessment.questions_assigned", entity_type="assessment",
        entity_id=assessment.id, actor=user,
        payload={
            "count": touched,
            "assigned_to": payload.assigned_to_id,
            "due_at": payload.due_at.isoformat() if payload.due_at else None,
        },
        ip_address=client_ip(request),
    )
    db.commit()
    return {"assigned": touched, "assigned_to_id": payload.assigned_to_id}


@router.patch("/assessments/{assessment_id}/due-date", response_model=dict)
def set_due_date(
    payload: AssessmentDueIn,
    request: Request,
    assessment: Assessment = Depends(get_assessment),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if not can_manage_org(user):
        raise APIError("auth.forbidden", status.HTTP_403_FORBIDDEN)
    assessment.due_at = payload.due_at
    audit.record(
        db, action="assessment.due_date_set", entity_type="assessment",
        entity_id=assessment.id, actor=user,
        payload={"due_at": payload.due_at.isoformat() if payload.due_at else None},
        ip_address=client_ip(request),
    )
    db.commit()
    return {"due_at": assessment.due_at.isoformat() if assessment.due_at else None}


@router.get("/assessments/{assessment_id}/progress/by-user", response_model=list[dict])
def progress_by_user(
    assessment: Assessment = Depends(get_assessment), db: Session = Depends(get_db)
) -> list[dict]:
    """FR-12 — completion by user."""
    return assessment_service.progress_by_user(db, assessment)


@router.get("/assessments/{assessment_id}/overdue", response_model=list[dict])
def overdue(
    assessment: Assessment = Depends(get_assessment), db: Session = Depends(get_db)
) -> list[dict]:
    """FR-12 — overdue items."""
    return assessment_service.overdue_items(db, assessment)


@router.get("/assessments/{assessment_id}/comparison", response_model=dict | None)
def comparison(
    assessment: Assessment = Depends(get_assessment), db: Session = Depends(get_db)
) -> dict | None:
    """Report section 9 — comparison to the organisation's prior assessment."""
    return assessment_service.comparison(db, assessment)


