"""Expert sessions — the Layer 3 offering in BRD section 10.

What actually distinguishes the top service layer from a report: a scheduled
working meeting with an iValue expert, tracked through request → scheduled →
completed with its notes attached to the assessment. Gated on the
`expert_review` entitlement, so the layer boundary is enforced here and not
only in a pricing table.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, get_assessment, get_current_user, require_ivalue
from app.core.errors import APIError
from app.core.security import utcnow
from app.db.session import get_db
from app.models import (
    Assessment,
    ExpertSession,
    User,
)
from app.services import audit, entitlements

router = APIRouter(tags=["governance"])



class SessionRequestIn(BaseModel):
    preferred_slots: list[datetime] = Field(default_factory=list)
    agenda: str | None = None


class SessionScheduleIn(BaseModel):
    scheduled_at: datetime
    duration_minutes: int = Field(default=60, ge=15, le=240)
    meeting_url: str | None = None
    notes: str | None = None


def _session_dict(row: ExpertSession, db: Session) -> dict:
    expert = db.get(User, row.expert_id) if row.expert_id else None
    return {
        "id": row.id,
        "assessment_id": row.assessment_id,
        "status": row.status,
        "preferred_slots": row.preferred_slots,
        "scheduled_at": row.scheduled_at.isoformat() if row.scheduled_at else None,
        "duration_minutes": row.duration_minutes,
        "meeting_url": row.meeting_url,
        "agenda": row.agenda,
        "notes": row.notes,
        "expert_name": expert.full_name if expert else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "created_at": row.created_at.isoformat(),
    }


@router.get("/assessments/{assessment_id}/expert-sessions", response_model=list[dict])
def list_sessions(
    assessment: Assessment = Depends(get_assessment), db: Session = Depends(get_db)
) -> list[dict]:
    rows = db.scalars(
        select(ExpertSession)
        .where(ExpertSession.assessment_id == assessment.id)
        .order_by(ExpertSession.created_at.desc())
    )
    return [_session_dict(r, db) for r in rows]


@router.post("/assessments/{assessment_id}/expert-sessions", response_model=dict, status_code=201)
def request_session(
    payload: SessionRequestIn,
    request: Request,
    assessment: Assessment = Depends(get_assessment),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """The deep-dive layer includes an online meeting with an expert. The
    customer proposes slots; iValue confirms one."""
    entitlements.require(assessment, entitlements.Feature.EXPERT_REVIEW, user)

    session = ExpertSession(
        assessment_id=assessment.id,
        requested_by_id=user.id,
        status="requested",
        preferred_slots=[slot.isoformat() for slot in payload.preferred_slots],
        agenda=payload.agenda,
    )
    db.add(session)
    db.flush()
    audit.record(
        db, action="expert_session.requested", entity_type="expert_session",
        entity_id=session.id, actor=user, organization_id=assessment.organization_id,
        payload={"slots": len(payload.preferred_slots)}, ip_address=client_ip(request),
    )
    db.commit()
    return _session_dict(session, db)


@router.patch("/expert-sessions/{session_id}/schedule", response_model=dict)
def schedule_session(
    session_id: str,
    payload: SessionScheduleIn,
    request: Request,
    user: User = Depends(require_ivalue),
    db: Session = Depends(get_db),
) -> dict:
    session = db.get(ExpertSession, session_id)
    if session is None:
        raise APIError("expert_session.not_found", status.HTTP_404_NOT_FOUND)
    session.status = "scheduled"
    session.expert_id = user.id
    session.scheduled_at = payload.scheduled_at
    session.duration_minutes = payload.duration_minutes
    session.meeting_url = payload.meeting_url
    session.notes = payload.notes
    audit.record(
        db, action="expert_session.scheduled", entity_type="expert_session",
        entity_id=session.id, actor=user,
        payload={"scheduled_at": payload.scheduled_at.isoformat()},
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(session)
    return _session_dict(session, db)


@router.patch("/expert-sessions/{session_id}/complete", response_model=dict)
def complete_session(
    session_id: str,
    payload: dict,
    request: Request,
    user: User = Depends(require_ivalue),
    db: Session = Depends(get_db),
) -> dict:
    session = db.get(ExpertSession, session_id)
    if session is None:
        raise APIError("expert_session.not_found", status.HTTP_404_NOT_FOUND)
    session.status = "completed"
    session.completed_at = utcnow()
    if payload.get("notes"):
        session.notes = payload["notes"]
    audit.record(
        db, action="expert_session.completed", entity_type="expert_session",
        entity_id=session.id, actor=user, ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(session)
    return _session_dict(session, db)
