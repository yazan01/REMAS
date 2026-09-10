"""Bridges the ORM to the pure scoring engine."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Assessment,
    Axis,
    DocumentLink,
    EvidenceStatus,
    FrameworkVersion,
    Question,
    Response,
    ScoringRun,
    User,
)
from app.services import scoring

EVIDENCE_ACCEPTED = {
    EvidenceStatus.UPLOADED,
    EvidenceStatus.AI_REVIEWED,
    EvidenceStatus.VALIDATED,
}


def selected_axes(db: Session, assessment: Assessment) -> list[Axis]:
    stmt = (
        select(Axis)
        .where(Axis.framework_version_id == assessment.framework_version_id)
        .options(selectinload(Axis.questions))
        .order_by(Axis.order_index)
    )
    axes = list(db.scalars(stmt))
    chosen = set(assessment.selected_axis_ids or [])
    if chosen:
        axes = [a for a in axes if a.id in chosen]
    return axes


def _responses_by_question(db: Session, assessment_id: str) -> dict[str, Response]:
    rows = db.scalars(select(Response).where(Response.assessment_id == assessment_id))
    return {r.question_id: r for r in rows}


def _evidence_by_question(db: Session, assessment_id: str) -> dict[str, list[DocumentLink]]:
    rows = db.scalars(
        select(DocumentLink).where(DocumentLink.assessment_id == assessment_id)
    )
    out: dict[str, list[DocumentLink]] = {}
    for link in rows:
        out.setdefault(link.question_id, []).append(link)
    return out


def completion_for_many(
    db: Session, assessments: list[Assessment]
) -> dict[str, float]:
    """Answered-fraction for a whole list, in two queries instead of eight each.

    `progress()` is the detail computation: per-axis counts, missing evidence,
    overdue items. A list view needs one number from it, and calling it per row
    cost eight queries per assessment — measured at 10 for one assessment and 34
    for four, i.e. linear growth on the customer's main dashboard endpoint.

    This batches the *loading* and keeps the *logic*: the answered predicate is
    still `Response.is_answered`, so a completion percentage computed here can
    never drift from one computed by `progress()`. Translating that property
    into SQL would have been faster still and is exactly how the two would have
    silently disagreed.
    """
    if not assessments:
        return {}

    version_ids = {a.framework_version_id for a in assessments}
    axis_rows = db.scalars(
        select(Axis)
        .where(Axis.framework_version_id.in_(version_ids))
        .options(selectinload(Axis.questions))
    )
    questions_by_axis: dict[str, int] = {}
    axes_by_version: dict[str, list[Axis]] = {}
    for axis in axis_rows:
        questions_by_axis[axis.id] = len(axis.questions)
        axes_by_version.setdefault(axis.framework_version_id, []).append(axis)

    assessment_ids = [a.id for a in assessments]
    answered_by_assessment: dict[str, int] = {a.id: 0 for a in assessments}
    for response in db.scalars(
        select(Response).where(Response.assessment_id.in_(assessment_ids))
    ):
        if response.is_answered:
            answered_by_assessment[response.assessment_id] = (
                answered_by_assessment.get(response.assessment_id, 0) + 1
            )

    out: dict[str, float] = {}
    for assessment in assessments:
        axes = axes_by_version.get(assessment.framework_version_id, [])
        chosen = set(assessment.selected_axis_ids or [])
        if chosen:
            axes = [a for a in axes if a.id in chosen]
        total = sum(questions_by_axis.get(a.id, 0) for a in axes)
        answered = answered_by_assessment.get(assessment.id, 0)
        out[assessment.id] = round(answered / total, 4) if total else 0.0
    return out


def latest_runs_for_many(
    db: Session, assessments: list[Assessment]
) -> dict[str, ScoringRun]:
    """The most recent scoring run per assessment, in one query.

    Ordered oldest-first so the dictionary write for each assessment ends on the
    newest row — the same answer as one `ORDER BY created_at DESC LIMIT 1` per
    assessment, without the per-row round trip.
    """
    if not assessments:
        return {}
    runs: dict[str, ScoringRun] = {}
    for run in db.scalars(
        select(ScoringRun)
        .where(ScoringRun.assessment_id.in_([a.id for a in assessments]))
        .order_by(ScoringRun.created_at)
    ):
        runs[run.assessment_id] = run
    return runs


def build_inputs(db: Session, assessment: Assessment) -> list[scoring.AxisInput]:
    responses = _responses_by_question(db, assessment.id)
    evidence = _evidence_by_question(db, assessment.id)
    inputs: list[scoring.AxisInput] = []

    for axis in selected_axes(db, assessment):
        questions: list[scoring.QuestionInput] = []
        for question in axis.questions:
            response = responses.get(question.id)
            links = evidence.get(question.id, [])
            has_evidence = any(link.status in EVIDENCE_ACCEPTED for link in links)

            if response is None:
                source = "unanswered"
                score = None
                is_na = False
            elif response.is_not_applicable:
                source = "not_applicable"
                score = None
                is_na = True
            elif response.override_score is not None:
                source = "override"
                score = response.override_score
                is_na = False
            else:
                source = "answer"
                score = response.score
                is_na = False

            questions.append(
                scoring.QuestionInput(
                    id=question.id,
                    code=question.code,
                    weight=question.weight,
                    score=score,
                    is_not_applicable=is_na,
                    is_mandatory=question.is_mandatory,
                    evidence_required=question.evidence_required,
                    has_evidence=has_evidence,
                    source=source,
                )
            )

        inputs.append(
            scoring.AxisInput(
                id=axis.id,
                code=axis.code,
                weight=axis.weight,
                questions=questions,
            )
        )
    return inputs


def effective_config(db: Session, assessment: Assessment) -> dict[str, Any]:
    """A submitted assessment keeps the config it was scored with; an open one
    reads the live framework version (BRD FR-22)."""
    if assessment.scoring_snapshot:
        return assessment.scoring_snapshot
    version = db.get(FrameworkVersion, assessment.framework_version_id)
    return dict(version.scoring_config) if version else {}


def calculate(db: Session, assessment: Assessment) -> scoring.ScoringResult:
    return scoring.compute(build_inputs(db, assessment), effective_config(db, assessment))


def record_run(
    db: Session,
    assessment: Assessment,
    result: scoring.ScoringResult,
    *,
    actor: User | None = None,
    reason: str | None = None,
) -> ScoringRun:
    run = ScoringRun(
        assessment_id=assessment.id,
        triggered_by_id=actor.id if actor else None,
        reason=reason,
        overall_score=result.overall_score,
        maturity_level=result.maturity_level,
        config_used=result.config,
        result=result.as_dict(),
    )
    db.add(run)
    return run


def progress(db: Session, assessment: Assessment) -> dict[str, Any]:
    """Completion view used by the questionnaire header and the reviewer's
    progress screen (BRD FR-10 / FR-12)."""
    axes = selected_axes(db, assessment)
    responses = _responses_by_question(db, assessment.id)
    evidence = _evidence_by_question(db, assessment.id)

    per_axis = []
    total = answered = mandatory_open = 0
    for axis in axes:
        a_total = len(axis.questions)
        a_answered = 0
        a_mandatory_open = 0
        a_evidence_missing = 0
        for question in axis.questions:
            response = responses.get(question.id)
            if response and response.is_answered:
                a_answered += 1
            elif question.is_mandatory:
                a_mandatory_open += 1
            if question.evidence_required and not any(
                link.status in EVIDENCE_ACCEPTED for link in evidence.get(question.id, [])
            ):
                a_evidence_missing += 1
        total += a_total
        answered += a_answered
        mandatory_open += a_mandatory_open
        per_axis.append(
            {
                "axis_id": axis.id,
                "code": axis.code,
                "name_ar": axis.name_ar,
                "name_en": axis.name_en,
                "total_questions": a_total,
                "answered_questions": a_answered,
                "unanswered_mandatory": a_mandatory_open,
                "missing_evidence": a_evidence_missing,
                "completion": round(a_answered / a_total, 4) if a_total else 0.0,
            }
        )

    return {
        "assessment_id": assessment.id,
        "status": assessment.status,
        "total_questions": total,
        "answered_questions": answered,
        "unanswered_mandatory": mandatory_open,
        "completion": round(answered / total, 4) if total else 0.0,
        "can_submit": mandatory_open == 0 and answered > 0,
        "axes": per_axis,
        "overdue": len(overdue_items(db, assessment)),
    }


def _is_overdue(response, assessment_due, now) -> bool:
    """Unanswered past its deadline. An answered question is never overdue."""
    if response is not None and response.is_answered:
        return False
    from app.core.security import as_aware

    deadline = as_aware(response.due_at) if response is not None and response.due_at else None
    deadline = deadline or as_aware(assessment_due)
    return bool(deadline and deadline < now)


def progress_by_user(db: Session, assessment: Assessment) -> list[dict[str, Any]]:
    """FR-12 - completion by user, over the questions assigned to each of them."""
    from app.core.security import utcnow
    from app.models import User as UserModel

    now = utcnow()
    responses = _responses_by_question(db, assessment.id)
    questions = [q for axis in selected_axes(db, assessment) for q in axis.questions]

    buckets: dict[str | None, dict[str, Any]] = {}
    for question in questions:
        response = responses.get(question.id)
        owner = response.assigned_to_id if response else None
        bucket = buckets.setdefault(
            owner, {"user_id": owner, "assigned": 0, "answered": 0, "overdue": 0}
        )
        bucket["assigned"] += 1
        if response and response.is_answered:
            bucket["answered"] += 1
        if _is_overdue(response, assessment.due_at, now):
            bucket["overdue"] += 1

    out: list[dict[str, Any]] = []
    for owner, bucket in buckets.items():
        user = db.get(UserModel, owner) if owner else None
        bucket["full_name"] = user.full_name if user else None
        bucket["email"] = user.email if user else None
        bucket["completion"] = (
            round(bucket["answered"] / bucket["assigned"], 4) if bucket["assigned"] else 0.0
        )
        out.append(bucket)
    out.sort(key=lambda b: (b["user_id"] is None, -b["overdue"], b["completion"]))
    return out


def overdue_items(db: Session, assessment: Assessment) -> list[dict[str, Any]]:
    """FR-12 - the overdue list the reviewer progress view needs."""
    from app.core.security import as_aware, utcnow
    from app.models import User as UserModel

    now = utcnow()
    responses = _responses_by_question(db, assessment.id)
    out: list[dict[str, Any]] = []
    for axis in selected_axes(db, assessment):
        for question in axis.questions:
            response = responses.get(question.id)
            if not _is_overdue(response, assessment.due_at, now):
                continue
            owner = (
                db.get(UserModel, response.assigned_to_id)
                if response and response.assigned_to_id
                else None
            )
            deadline = (
                as_aware(response.due_at)
                if response and response.due_at
                else as_aware(assessment.due_at)
            )
            out.append(
                {
                    "question_id": question.id,
                    "question_code": question.code,
                    "axis_id": axis.id,
                    "axis_code": axis.code,
                    "assigned_to": owner.full_name if owner else None,
                    "assigned_to_email": owner.email if owner else None,
                    "due_at": deadline.isoformat() if deadline else None,
                    "days_overdue": (now - deadline).days if deadline else None,
                    "is_mandatory": question.is_mandatory,
                }
            )
    out.sort(key=lambda r: -(r["days_overdue"] or 0))
    return out


def prior_assessment(db: Session, assessment: Assessment) -> Assessment | None:
    """The organisation previous completed assessment on the same framework -
    what the report comparison section needs."""
    stmt = (
        select(Assessment)
        .where(
            Assessment.organization_id == assessment.organization_id,
            Assessment.id != assessment.id,
            Assessment.framework_version_id == assessment.framework_version_id,
            Assessment.submitted_at.isnot(None),
        )
        .order_by(Assessment.submitted_at.desc())
    )
    if assessment.submitted_at:
        stmt = stmt.where(Assessment.submitted_at < assessment.submitted_at)
    return db.scalars(stmt).first()


def comparison(db: Session, assessment: Assessment) -> dict[str, Any] | None:
    """Axis-by-axis delta against the previous assessment, or None if this is
    the organisation first."""
    previous = prior_assessment(db, assessment)
    if previous is None:
        return None

    latest_run = db.scalars(
        select(ScoringRun)
        .where(ScoringRun.assessment_id == previous.id)
        .order_by(ScoringRun.created_at.desc())
    ).first()
    old = (
        latest_run.result
        if latest_run and latest_run.result
        else calculate(db, previous).as_dict()
    )
    new = calculate(db, assessment).as_dict()

    old_by_axis = {row["axis_id"]: row for row in old["axes"]}
    axes = []
    for row in new["axes"]:
        before = old_by_axis.get(row["axis_id"])
        if not before or before.get("score") is None or row.get("score") is None:
            continue
        axes.append(
            {
                "axis_id": row["axis_id"],
                "code": row["code"],
                "previous": before["score"],
                "current": row["score"],
                "delta": round(row["score"] - before["score"], 2),
            }
        )

    overall_delta = None
    if old.get("overall_score") is not None and new.get("overall_score") is not None:
        overall_delta = round(new["overall_score"] - old["overall_score"], 2)

    return {
        "previous_assessment_id": previous.id,
        "previous_name": previous.name,
        "previous_submitted_at": previous.submitted_at.isoformat()
        if previous.submitted_at
        else None,
        "previous_overall": old.get("overall_score"),
        "current_overall": new.get("overall_score"),
        "overall_delta": overall_delta,
        "axes": axes,
    }


def review_deltas(db: Session, assessment: Assessment, threshold: int = 1) -> list[dict[str, Any]]:
    """FR-24 — material score differences between the customer's answer and the
    reviewer's override. A difference of `threshold` levels or more is material."""
    rows = db.scalars(
        select(Response).where(
            Response.assessment_id == assessment.id, Response.override_score.isnot(None)
        )
    )
    out: list[dict[str, Any]] = []
    for response in rows:
        question = db.get(Question, response.question_id)
        if question is None or response.score is None:
            continue
        delta = response.override_score - response.score
        if abs(delta) < threshold:
            continue
        axis = db.get(Axis, question.axis_id)
        out.append(
            {
                "question_id": question.id,
                "question_code": question.code,
                "axis_id": question.axis_id,
                "axis_code": axis.code if axis else None,
                "customer_score": response.score,
                "reviewer_score": response.override_score,
                "delta": delta,
                "reason": response.override_reason,
                "is_material": abs(delta) >= 2,
            }
        )
    out.sort(key=lambda r: -abs(r["delta"]))
    return out


def clarification_items(db: Session, assessment: Assessment) -> list[dict[str, Any]]:
    """FR-24 — questions whose evidence a reviewer or the AI has flagged."""
    from app.models import Document

    flagged = {EvidenceStatus.REQUIRES_CLARIFICATION, EvidenceStatus.REJECTED}
    out: list[dict[str, Any]] = []
    for link in db.scalars(
        select(DocumentLink).where(
            DocumentLink.assessment_id == assessment.id, DocumentLink.status.in_(flagged)
        )
    ):
        question = db.get(Question, link.question_id)
        document = db.get(Document, link.document_id)
        out.append(
            {
                "question_id": link.question_id,
                "question_code": question.code if question else None,
                "axis_id": question.axis_id if question else None,
                "document_id": link.document_id,
                "filename": document.filename if document else None,
                "status": link.status,
                "reviewer_note": link.reviewer_note,
            }
        )
    return out


def missing_questions(db: Session, assessment: Assessment) -> list[Question]:
    responses = _responses_by_question(db, assessment.id)
    out: list[Question] = []
    for axis in selected_axes(db, assessment):
        for question in axis.questions:
            response = responses.get(question.id)
            if question.is_mandatory and not (response and response.is_answered):
                out.append(question)
    return out
