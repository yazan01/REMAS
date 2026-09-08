from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, get_assessment, get_current_user, require_ivalue
from app.api.routes.frameworks import current_published_version
from app.core.errors import APIError
from app.core.security import utcnow
from app.db.session import get_db
from app.models import (
    Assessment,
    AssessmentStatus,
    Axis,
    FrameworkVersion,
    Question,
    Response,
    ScoringRun,
    User,
)
from app.models.enums import IVALUE_ROLES
from app.schemas import (
    AssessmentCreate,
    AssessmentDetail,
    AssessmentSummary,
    OverrideIn,
    ProgressOut,
    ResponseIn,
    ResponseOut,
    ScoringOut,
)
from app.services import assessment_service, audit

router = APIRouter(prefix="/assessments", tags=["assessments"])


def _latest_run(db: Session, assessment_id: str) -> ScoringRun | None:
    return db.scalars(
        select(ScoringRun)
        .where(ScoringRun.assessment_id == assessment_id)
        .order_by(ScoringRun.created_at.desc())
    ).first()


def _summary(db: Session, assessment: Assessment) -> AssessmentSummary:
    run = _latest_run(db, assessment.id)
    progress = assessment_service.progress(db, assessment)
    return AssessmentSummary(
        id=assessment.id,
        name=assessment.name,
        layer=assessment.layer,
        status=assessment.status,
        locked=assessment.locked,
        created_at=assessment.created_at,
        submitted_at=assessment.submitted_at,
        framework_version_id=assessment.framework_version_id,
        completion=progress["completion"],
        overall_score=run.overall_score if run else None,
        maturity_level=run.maturity_level if run else None,
    )


def _question_ids(db: Session, assessment: Assessment) -> set[str]:
    return {
        q.id for axis in assessment_service.selected_axes(db, assessment) for q in axis.questions
    }


def _assert_open(assessment: Assessment) -> None:
    if assessment.locked:
        raise APIError("assessment.locked", status.HTTP_409_CONFLICT)
    if assessment.status in (AssessmentStatus.SUBMITTED, AssessmentStatus.COMPLETED):
        raise APIError("assessment.already_submitted", status.HTTP_409_CONFLICT)


@router.get("", response_model=list[AssessmentSummary])
def list_assessments(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[AssessmentSummary]:
    stmt = select(Assessment).order_by(Assessment.created_at.desc())
    if user.role not in IVALUE_ROLES:
        stmt = stmt.where(Assessment.organization_id == user.organization_id)
    return [_summary(db, a) for a in db.scalars(stmt)]


@router.post("", response_model=AssessmentDetail, status_code=status.HTTP_201_CREATED)
def create_assessment(
    payload: AssessmentCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AssessmentDetail:
    if payload.framework_version_id:
        version = db.get(FrameworkVersion, payload.framework_version_id)
        if version is None:
            raise APIError("framework.not_found", status.HTTP_404_NOT_FOUND)
    else:
        version = current_published_version(db)

    valid_axis_ids = {a.id for a in version.axes}
    chosen = [a for a in payload.selected_axis_ids if a in valid_axis_ids]

    assessment = Assessment(
        organization_id=user.organization_id,
        framework_version_id=version.id,
        name=payload.name,
        layer=payload.layer,
        status=AssessmentStatus.DRAFT,
        selected_axis_ids=chosen,
        created_by_id=user.id,
    )
    db.add(assessment)
    db.flush()
    audit.record(
        db,
        action="assessment.created",
        entity_type="assessment",
        entity_id=assessment.id,
        actor=user,
        payload={"layer": payload.layer, "framework_version": version.id},
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(assessment)

    summary = _summary(db, assessment)
    return AssessmentDetail(
        **summary.model_dump(),
        selected_axis_ids=assessment.selected_axis_ids or [],
        organization_id=assessment.organization_id,
    )


@router.get("/{assessment_id}", response_model=AssessmentDetail)
def get_one(
    assessment: Assessment = Depends(get_assessment), db: Session = Depends(get_db)
) -> AssessmentDetail:
    summary = _summary(db, assessment)
    return AssessmentDetail(
        **summary.model_dump(),
        selected_axis_ids=assessment.selected_axis_ids or [],
        organization_id=assessment.organization_id,
    )


@router.get("/{assessment_id}/progress", response_model=ProgressOut)
def get_progress(
    assessment: Assessment = Depends(get_assessment), db: Session = Depends(get_db)
) -> dict:
    return assessment_service.progress(db, assessment)


@router.get("/{assessment_id}/responses", response_model=list[ResponseOut])
def list_responses(
    assessment: Assessment = Depends(get_assessment), db: Session = Depends(get_db)
) -> list[Response]:
    return list(db.scalars(select(Response).where(Response.assessment_id == assessment.id)))


@router.put("/{assessment_id}/responses", response_model=list[ResponseOut])
def save_responses(
    payload: list[ResponseIn],
    request: Request,
    assessment: Assessment = Depends(get_assessment),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Response]:
    """Auto-save endpoint (BRD FR-10). Idempotent upsert of one or more answers,
    so the client can batch a debounced save without tracking creates vs updates."""
    _assert_open(assessment)
    allowed = _question_ids(db, assessment)
    existing = {
        r.question_id: r
        for r in db.scalars(select(Response).where(Response.assessment_id == assessment.id))
    }
    touched: list[Response] = []

    for item in payload:
        if item.question_id not in allowed:
            raise APIError("question.not_in_assessment", status.HTTP_400_BAD_REQUEST)
        question = db.get(Question, item.question_id)
        if question is None:
            raise APIError("question.not_in_assessment", status.HTTP_400_BAD_REQUEST)
        if item.is_not_applicable and not question.allow_not_applicable:
            raise APIError("question.na_not_allowed", status.HTTP_400_BAD_REQUEST)
        if not item.is_not_applicable and item.score is None:
            raise APIError("response.score_required", status.HTTP_400_BAD_REQUEST)

        response = existing.get(item.question_id)
        if response is None:
            response = Response(assessment_id=assessment.id, question_id=item.question_id)
            db.add(response)
            existing[item.question_id] = response

        response.score = item.score
        response.is_not_applicable = item.is_not_applicable
        response.na_rationale = item.na_rationale
        response.comment = item.comment
        response.answered_by_id = user.id
        touched.append(response)

    if assessment.status == AssessmentStatus.DRAFT and touched:
        assessment.status = AssessmentStatus.IN_PROGRESS

    audit.record(
        db,
        action="assessment.responses_saved",
        entity_type="assessment",
        entity_id=assessment.id,
        actor=user,
        payload={"question_ids": [r.question_id for r in touched]},
        ip_address=client_ip(request),
    )
    db.commit()
    for response in touched:
        db.refresh(response)
    return touched


@router.post("/{assessment_id}/submit", response_model=ScoringOut)
def submit(
    request: Request,
    assessment: Assessment = Depends(get_assessment),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    _assert_open(assessment)
    outstanding = assessment_service.missing_questions(db, assessment)
    if outstanding:
        raise APIError(
            "assessment.mandatory_incomplete",
            status.HTTP_409_CONFLICT,
            {"question_codes": [q.code for q in outstanding][:20], "count": len(outstanding)},
        )

    version = db.get(FrameworkVersion, assessment.framework_version_id)
    # Freeze the scoring rules in force at submission (BRD FR-22).
    assessment.scoring_snapshot = dict(version.scoring_config) if version else {}
    assessment.status = AssessmentStatus.SUBMITTED
    assessment.submitted_at = utcnow()
    assessment.submitted_by_id = user.id

    result = assessment_service.calculate(db, assessment)
    assessment_service.record_run(db, assessment, result, actor=user, reason="submission")
    audit.record(
        db,
        action="assessment.submitted",
        entity_type="assessment",
        entity_id=assessment.id,
        actor=user,
        payload={"overall_score": result.overall_score, "maturity_level": result.maturity_level},
        ip_address=client_ip(request),
    )
    db.commit()
    return result.as_dict()


@router.get("/{assessment_id}/results", response_model=ScoringOut)
def results(
    assessment: Assessment = Depends(get_assessment),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if assessment.status in (AssessmentStatus.DRAFT, AssessmentStatus.IN_PROGRESS):
        if user.role not in IVALUE_ROLES:
            raise APIError("assessment.not_submitted", status.HTTP_409_CONFLICT)
        # iValue reviewers can see a provisional calculation before submission.
    run = _latest_run(db, assessment.id)
    if run and run.result:
        return run.result
    return assessment_service.calculate(db, assessment).as_dict()


@router.post("/{assessment_id}/recalculate", response_model=ScoringOut)
def recalculate(
    request: Request,
    assessment: Assessment = Depends(get_assessment),
    user: User = Depends(require_ivalue),
    db: Session = Depends(get_db),
) -> dict:
    result = assessment_service.calculate(db, assessment)
    assessment_service.record_run(db, assessment, result, actor=user, reason="manual_recalculation")
    audit.record(
        db,
        action="assessment.recalculated",
        entity_type="assessment",
        entity_id=assessment.id,
        actor=user,
        payload={"overall_score": result.overall_score},
        ip_address=client_ip(request),
    )
    db.commit()
    return result.as_dict()


@router.post("/{assessment_id}/questions/{question_id}/override", response_model=ResponseOut)
def override_score(
    question_id: str,
    payload: OverrideIn,
    request: Request,
    assessment: Assessment = Depends(get_assessment),
    user: User = Depends(require_ivalue),
    db: Session = Depends(get_db),
) -> Response:
    """Reviewer override (BRD FR-23). The customer's answer is never overwritten:
    the override lives beside it so the delta stays reportable and the underlying
    calculation stays deterministic (FR-24, FR-26)."""
    if question_id not in _question_ids(db, assessment):
        raise APIError("question.not_in_assessment", status.HTTP_400_BAD_REQUEST)
    if payload.score is None and not payload.mark_not_applicable:
        raise APIError("response.score_required", status.HTTP_400_BAD_REQUEST)

    response = db.scalars(
        select(Response).where(
            Response.assessment_id == assessment.id, Response.question_id == question_id
        )
    ).first()
    if response is None:
        response = Response(assessment_id=assessment.id, question_id=question_id)
        db.add(response)

    previous = response.effective_score
    if payload.mark_not_applicable:
        response.is_not_applicable = True
        response.na_rationale = payload.reason
        response.override_score = None
    else:
        response.is_not_applicable = False
        response.override_score = payload.score
    response.override_reason = payload.reason
    response.override_by_id = user.id
    response.override_at = utcnow()

    audit.record(
        db,
        action="assessment.score_overridden",
        entity_type="response",
        entity_id=response.id,
        actor=user,
        organization_id=assessment.organization_id,
        payload={
            "question_id": question_id,
            "previous": previous,
            "new": response.effective_score,
            "not_applicable": response.is_not_applicable,
            "reason": payload.reason,
        },
        ip_address=client_ip(request),
    )
    result = assessment_service.calculate(db, assessment)
    assessment_service.record_run(db, assessment, result, actor=user, reason="score_override")
    db.commit()
    db.refresh(response)
    return response


@router.get("/{assessment_id}/axes", response_model=list[dict])
def list_selected_axes(
    assessment: Assessment = Depends(get_assessment), db: Session = Depends(get_db)
) -> list[dict]:
    axes: list[Axis] = assessment_service.selected_axes(db, assessment)
    return [
        {
            "id": axis.id,
            "code": axis.code,
            "order_index": axis.order_index,
            "name_ar": axis.name_ar,
            "name_en": axis.name_en,
            "weight": axis.weight,
            "question_count": len(axis.questions),
        }
        for axis in axes
    ]
