from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, get_assessment, get_current_user, require_ivalue
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
from app.services import assessment_service, audit, framework_service

router = APIRouter(prefix="/assessments", tags=["assessments"])


def _latest_run(db: Session, assessment_id: str) -> ScoringRun | None:
    return db.scalars(
        select(ScoringRun)
        .where(ScoringRun.assessment_id == assessment_id)
        .order_by(ScoringRun.created_at.desc())
    ).first()


def _build_summary(
    assessment: Assessment, completion: float, run: ScoringRun | None
) -> AssessmentSummary:
    return AssessmentSummary(
        id=assessment.id,
        name=assessment.name,
        layer=assessment.layer,
        status=assessment.status,
        locked=assessment.locked,
        created_at=assessment.created_at,
        submitted_at=assessment.submitted_at,
        framework_version_id=assessment.framework_version_id,
        completion=completion,
        overall_score=run.overall_score if run else None,
        maturity_level=run.maturity_level if run else None,
    )


def _summary(db: Session, assessment: Assessment) -> AssessmentSummary:
    """One assessment. The list endpoint uses `_summaries` instead — calling
    this in a loop is what made GET /assessments cost eight queries a row."""
    return _build_summary(
        assessment,
        assessment_service.progress(db, assessment)["completion"],
        _latest_run(db, assessment.id),
    )


def _summaries(db: Session, assessments: list[Assessment]) -> list[AssessmentSummary]:
    """A whole list, in a fixed number of queries regardless of its length."""
    completion = assessment_service.completion_for_many(db, assessments)
    runs = assessment_service.latest_runs_for_many(db, assessments)
    return [
        _build_summary(a, completion.get(a.id, 0.0), runs.get(a.id))
        for a in assessments
    ]


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
    return _summaries(db, list(db.scalars(stmt)))


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
        version = framework_service.current_published_version(db)

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
    override_incomplete: bool = Query(
        default=False,
        description="Submit despite unanswered mandatory questions. iValue only (FR-10).",
    ),
    override_reason: str | None = Query(default=None),
    assessment: Assessment = Depends(get_assessment),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    _assert_open(assessment)
    outstanding = assessment_service.missing_questions(db, assessment)
    if outstanding:
        # FR-10 allows submission with gaps only under an authorised override.
        if not override_incomplete:
            raise APIError(
                "assessment.mandatory_incomplete",
                status.HTTP_409_CONFLICT,
                {"question_codes": [q.code for q in outstanding][:20], "count": len(outstanding)},
            )
        if user.role not in IVALUE_ROLES:
            raise APIError("assessment.override_not_permitted", status.HTTP_403_FORBIDDEN)
        audit.record(
            db,
            action="assessment.submitted_with_override",
            entity_type="assessment",
            entity_id=assessment.id,
            actor=user,
            payload={"missing": len(outstanding), "reason": override_reason},
            ip_address=client_ip(request),
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


@router.get("/{assessment_id}/review", response_model=dict)
def review_view(
    assessment: Assessment = Depends(get_assessment),
    user: User = Depends(require_ivalue),
    db: Session = Depends(get_db),
) -> dict:
    """The iValue reviewer's working view (FR-12 / FR-24): completion, the
    material differences between customer and reviewer scores, and every item
    still awaiting clarification."""
    return {
        "assessment": {
            "id": assessment.id,
            "name": assessment.name,
            "layer": assessment.layer,
            "status": assessment.status,
            "organization_id": assessment.organization_id,
            "submitted_at": assessment.submitted_at.isoformat()
            if assessment.submitted_at
            else None,
        },
        "progress": assessment_service.progress(db, assessment),
        "by_user": assessment_service.progress_by_user(db, assessment),
        "overdue": assessment_service.overdue_items(db, assessment),
        "score_deltas": assessment_service.review_deltas(db, assessment),
        "clarifications": assessment_service.clarification_items(db, assessment),
        "comparison": assessment_service.comparison(db, assessment),
    }


@router.get("/{assessment_id}/questions", response_model=list[dict])
def filtered_questions(
    axis_id: str | None = Query(default=None),
    answered: bool | None = Query(default=None),
    mandatory_only: bool = Query(default=False),
    evidence_status: str | None = Query(default=None),
    flagged: bool = Query(default=False, description="has an AI or reviewer flag"),
    q: str | None = Query(default=None, description="matches question text or evidence name"),
    assessment: Assessment = Depends(get_assessment),
    db: Session = Depends(get_db),
) -> list[dict]:
    """FR-11 — the full filter set: axis, completion status, evidence status,
    expected evidence name, mandatory items, and AI/reviewer flags."""
    from app.models import AIFinding, DocumentLink

    responses = {
        r.question_id: r
        for r in db.scalars(select(Response).where(Response.assessment_id == assessment.id))
    }
    links: dict[str, list] = {}
    for link in db.scalars(
        select(DocumentLink).where(DocumentLink.assessment_id == assessment.id)
    ):
        links.setdefault(link.question_id, []).append(link)
    flags: set[str] = {
        f.question_id
        for f in db.scalars(
            select(AIFinding).where(
                AIFinding.assessment_id == assessment.id, AIFinding.question_id.isnot(None)
            )
        )
        if f.severity in ("medium", "high")
    }
    for response in responses.values():
        if response.override_score is not None:
            flags.add(response.question_id)

    needle = (q or "").strip().lower()
    out: list[dict] = []
    for axis in assessment_service.selected_axes(db, assessment):
        if axis_id and axis.id != axis_id:
            continue
        for question in axis.questions:
            response = responses.get(question.id)
            is_answered = bool(response and response.is_answered)
            question_links = links.get(question.id, [])
            statuses = [link.status for link in question_links]
            current_status = statuses[0] if statuses else "missing"

            if answered is not None and is_answered != answered:
                continue
            if mandatory_only and not question.is_mandatory:
                continue
            if evidence_status and current_status != evidence_status:
                continue
            if flagged and question.id not in flags:
                continue
            if needle:
                haystack = " ".join(
                    filter(
                        None,
                        [
                            question.text_ar,
                            question.text_en,
                            question.evidence_hint_ar,
                            question.evidence_hint_en,
                            question.code,
                        ],
                    )
                ).lower()
                if needle not in haystack:
                    continue

            out.append(
                {
                    "question_id": question.id,
                    "code": question.code,
                    "axis_id": axis.id,
                    "axis_code": axis.code,
                    "text_ar": question.text_ar,
                    "text_en": question.text_en,
                    "evidence_hint_ar": question.evidence_hint_ar,
                    "evidence_hint_en": question.evidence_hint_en,
                    "is_mandatory": question.is_mandatory,
                    "evidence_required": question.evidence_required,
                    "answered": is_answered,
                    "score": response.score if response else None,
                    "effective_score": response.effective_score if response else None,
                    "is_not_applicable": bool(response and response.is_not_applicable),
                    "evidence_status": current_status,
                    "evidence_count": len(question_links),
                    "flagged": question.id in flags,
                    "assigned_to_id": response.assigned_to_id if response else None,
                    "due_at": response.due_at.isoformat()
                    if response and response.due_at
                    else None,
                }
            )
    return out
