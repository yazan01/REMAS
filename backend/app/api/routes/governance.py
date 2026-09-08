"""Report templates, question assignment and expert sessions.

Closes FR-34 (configurable report templates), FR-12 (assignment, deadlines,
overdue items, completion by user) and the Layer 3 expert meeting.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import can_manage_org, client_ip, get_assessment, get_current_user, require_ivalue
from app.core.errors import APIError
from app.core.security import utcnow
from app.db.session import get_db
from app.models import (
    DEFAULT_BRANDING,
    DEFAULT_SECTIONS,
    REPORT_SECTIONS,
    Assessment,
    ExpertSession,
    ReportTemplate,
    Response as ResponseRow,
    User,
)
from app.models.enums import IVALUE_ROLES
from app.services import assessment_service, audit

router = APIRouter(tags=["governance"])


# ───────────────────────── report templates (FR-34) ─────────────────────────


class TemplateIn(BaseModel):
    code: str = Field(min_length=2, max_length=40)
    name_ar: str
    name_en: str
    framework_version_id: str | None = None
    sections: list[dict] | None = None
    branding: dict | None = None
    copy_blocks: dict | None = None
    output_formats: list[str] | None = None
    maturity_labels: dict | None = None
    include_comparison: bool = True
    is_default: bool = False


class TemplatePatch(BaseModel):
    name_ar: str | None = None
    name_en: str | None = None
    sections: list[dict] | None = None
    branding: dict | None = None
    copy_blocks: dict | None = None
    output_formats: list[str] | None = None
    maturity_labels: dict | None = None
    include_comparison: bool | None = None
    is_default: bool | None = None
    is_active: bool | None = None


def _template_dict(row: ReportTemplate) -> dict:
    return {
        "id": row.id,
        "code": row.code,
        "name_ar": row.name_ar,
        "name_en": row.name_en,
        "framework_version_id": row.framework_version_id,
        "sections": row.sections,
        "branding": row.branding,
        "copy_blocks": row.copy_blocks,
        "output_formats": row.output_formats,
        "maturity_labels": row.maturity_labels,
        "include_comparison": row.include_comparison,
        "is_default": row.is_default,
        "is_active": row.is_active,
    }


@router.get("/admin/report-templates", response_model=dict)
def list_templates(
    _u: User = Depends(require_ivalue), db: Session = Depends(get_db)
) -> dict:
    rows = db.scalars(select(ReportTemplate).order_by(ReportTemplate.created_at))
    return {
        "templates": [_template_dict(r) for r in rows],
        "available_sections": REPORT_SECTIONS,
        "defaults": {"sections": DEFAULT_SECTIONS, "branding": DEFAULT_BRANDING},
    }


@router.post("/admin/report-templates", response_model=dict, status_code=201)
def create_template(
    payload: TemplateIn,
    request: Request,
    user: User = Depends(require_ivalue),
    db: Session = Depends(get_db),
) -> dict:
    existing = db.scalar(
        select(ReportTemplate).where(
            ReportTemplate.code == payload.code,
            ReportTemplate.framework_version_id == payload.framework_version_id,
        )
    )
    if existing:
        raise APIError("report.template_code_taken", status.HTTP_409_CONFLICT)

    data = payload.model_dump()
    data["sections"] = data.get("sections") or list(DEFAULT_SECTIONS)
    data["branding"] = {**DEFAULT_BRANDING, **(data.get("branding") or {})}
    data["copy_blocks"] = data.get("copy_blocks") or {}
    data["output_formats"] = data.get("output_formats") or ["pdf", "html", "json"]
    data["maturity_labels"] = data.get("maturity_labels") or {}

    template = ReportTemplate(**data)
    db.add(template)
    db.flush()
    if template.is_default:
        _clear_other_defaults(db, template)
    audit.record(
        db, action="admin.report_template_created", entity_type="report_template",
        entity_id=template.id, actor=user, payload={"code": template.code},
        ip_address=client_ip(request),
    )
    db.commit()
    return _template_dict(template)


@router.patch("/admin/report-templates/{template_id}", response_model=dict)
def update_template(
    template_id: str,
    payload: TemplatePatch,
    request: Request,
    user: User = Depends(require_ivalue),
    db: Session = Depends(get_db),
) -> dict:
    template = db.get(ReportTemplate, template_id)
    if template is None:
        raise APIError("report.template_not_found", status.HTTP_404_NOT_FOUND)

    changes = payload.model_dump(exclude_none=True)
    if "sections" in changes:
        keys = {item.get("key") for item in changes["sections"]}
        unknown = keys - set(REPORT_SECTIONS)
        if unknown:
            raise APIError(
                "report.unknown_section", status.HTTP_422_UNPROCESSABLE_CONTENT,
                {"unknown": sorted(str(k) for k in unknown)},
            )
    if "branding" in changes:
        changes["branding"] = {**(template.branding or {}), **changes["branding"]}
    for field, value in changes.items():
        setattr(template, field, value)
    if changes.get("is_default"):
        _clear_other_defaults(db, template)

    audit.record(
        db, action="admin.report_template_updated", entity_type="report_template",
        entity_id=template.id, actor=user, payload={"fields": sorted(changes)},
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(template)
    return _template_dict(template)


@router.delete(
    "/admin/report-templates/{template_id}",
    status_code=204,
    response_class=Response,
    response_model=None,
)
def delete_template(
    template_id: str,
    request: Request,
    user: User = Depends(require_ivalue),
    db: Session = Depends(get_db),
) -> None:
    template = db.get(ReportTemplate, template_id)
    if template is None:
        raise APIError("report.template_not_found", status.HTTP_404_NOT_FOUND)
    audit.record(
        db, action="admin.report_template_deleted", entity_type="report_template",
        entity_id=template.id, actor=user, ip_address=client_ip(request),
    )
    db.delete(template)
    db.commit()


def _clear_other_defaults(db: Session, template: ReportTemplate) -> None:
    """One default per scope, so `resolve_template` is never ambiguous."""
    for other in db.scalars(
        select(ReportTemplate).where(
            ReportTemplate.framework_version_id == template.framework_version_id,
            ReportTemplate.id != template.id,
        )
    ):
        other.is_default = False


# ──────────────── assignment, deadlines and overdue (FR-12) ─────────────────


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


# ───────────────────── expert sessions (Layer 3, section 10) ────────────────


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
    from app.api.routes.insights import require_feature

    require_feature(assessment, "expert_review", user)

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
