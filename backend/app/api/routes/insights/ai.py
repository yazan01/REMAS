"""The five-stage AI pipeline and the human review gate over its output.

Covers AI-01 → AI-07. The governing rule of the whole module, from FR-26: the
AI *suggests and explains, it never scores and never approves*. Every finding
lands as a proposal that a reviewer accepts or rejects; the numbers on the
report come from `services/scoring.py` alone, whichever provider produced the
prose.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import (
    client_ip,
    get_assessment,
    get_current_user,
    require_ivalue,
    require_submitted,
)
from app.core.config import settings
from app.core.errors import APIError
from app.core.security import utcnow
from app.db.session import get_db
from app.models import AIFinding, AIJob, Assessment, User
from app.services import audit, entitlements
from app.services.ai import pipeline

router = APIRouter(tags=["insights"])



class RunAIIn(BaseModel):
    stages: list[str] | None = None


@router.post("/assessments/{assessment_id}/ai/run", response_model=dict)
def run_ai(
    payload: RunAIIn,
    request: Request,
    assessment: Assessment = Depends(get_assessment),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Runs the pipeline. Evidence review is available to every layer; the
    narrative and recommendation stages need an AI-report layer or above."""
    if not settings.ai_enabled:
        raise APIError("ai.disabled", status.HTTP_503_SERVICE_UNAVAILABLE)

    stages = payload.stages or ["extract", "relevance", "analyse", "recommend"]
    if {"analyse", "recommend"} & set(stages):
        entitlements.require(assessment, entitlements.Feature.AI_ANALYSIS, user)
    else:
        entitlements.require(assessment, entitlements.Feature.EVIDENCE_AI_REVIEW, user)
    require_submitted(assessment, user)

    job = pipeline.run(db, assessment, actor=user, stages=stages)
    audit.record(
        db,
        action="ai.pipeline_run",
        entity_type="assessment",
        entity_id=assessment.id,
        actor=user,
        payload={"stages": stages, "status": job.status, "provider": job.provider,
                 "summary": job.summary},
        ip_address=client_ip(request),
    )
    db.commit()
    return {
        "job_id": job.id,
        "status": job.status,
        "provider": job.provider,
        "model": job.model,
        "summary": job.summary,
        "error": job.error,
    }


@router.get("/assessments/{assessment_id}/ai/jobs", response_model=list[dict])
def list_ai_jobs(
    assessment: Assessment = Depends(get_assessment), db: Session = Depends(get_db)
) -> list[dict]:
    rows = db.scalars(
        select(AIJob)
        .where(AIJob.assessment_id == assessment.id)
        .order_by(AIJob.created_at.desc())
    )
    return [
        {
            "id": job.id,
            "stage": job.stage,
            "status": job.status,
            "provider": job.provider,
            "model": job.model,
            "prompt_version": job.prompt_version,
            "summary": job.summary,
            "error": job.error,
            "created_at": job.created_at.isoformat(),
        }
        for job in rows
    ]


@router.get("/assessments/{assessment_id}/ai/findings", response_model=list[dict])
def list_findings(
    kind: str | None = Query(default=None),
    axis_id: str | None = Query(default=None),
    assessment: Assessment = Depends(get_assessment),
    db: Session = Depends(get_db),
) -> list[dict]:
    stmt = (
        select(AIFinding)
        .where(AIFinding.assessment_id == assessment.id)
        .order_by(AIFinding.created_at.desc())
    )
    if kind:
        stmt = stmt.where(AIFinding.kind == kind)
    if axis_id:
        stmt = stmt.where(AIFinding.axis_id == axis_id)
    return [_finding_dict(f) for f in db.scalars(stmt)]


def _finding_dict(finding: AIFinding) -> dict:
    return {
        "id": finding.id,
        "kind": finding.kind,
        "severity": finding.severity,
        "axis_id": finding.axis_id,
        "question_id": finding.question_id,
        "document_id": finding.document_id,
        "title_ar": finding.title_ar,
        "title_en": finding.title_en,
        "body_ar": finding.body_ar,
        "body_en": finding.body_en,
        "citation": finding.citation,
        "confidence": finding.confidence,
        "review_status": finding.review_status,
        "reviewer_note": finding.reviewer_note,
        "created_at": finding.created_at.isoformat(),
    }


class FindingReviewIn(BaseModel):
    review_status: str = Field(pattern="^(accepted|rejected|edited|draft)$")
    body_ar: str | None = None
    body_en: str | None = None
    reviewer_note: str | None = None


@router.patch("/ai/findings/{finding_id}", response_model=dict)
def review_finding(
    finding_id: str,
    payload: FindingReviewIn,
    request: Request,
    user: User = Depends(require_ivalue),
    db: Session = Depends(get_db),
) -> dict:
    """The human review gate the BRD requires over every AI output."""
    finding = db.get(AIFinding, finding_id)
    if finding is None:
        raise APIError("ai.finding_not_found", status.HTTP_404_NOT_FOUND)

    previous = finding.review_status
    finding.review_status = payload.review_status
    if payload.body_ar is not None:
        finding.body_ar = payload.body_ar
    if payload.body_en is not None:
        finding.body_en = payload.body_en
    finding.reviewer_note = payload.reviewer_note
    finding.reviewed_by_id = user.id
    finding.reviewed_at = utcnow()

    audit.record(
        db,
        action="ai.finding_reviewed",
        entity_type="ai_finding",
        entity_id=finding.id,
        actor=user,
        payload={"from": previous, "to": payload.review_status},
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(finding)
    return _finding_dict(finding)

