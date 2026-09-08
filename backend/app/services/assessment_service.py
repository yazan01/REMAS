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
    }


def missing_questions(db: Session, assessment: Assessment) -> list[Question]:
    responses = _responses_by_question(db, assessment.id)
    out: list[Question] = []
    for axis in selected_axes(db, assessment):
        for question in axis.questions:
            response = responses.get(question.id)
            if question.is_mandatory and not (response and response.is_answered):
                out.append(question)
    return out
