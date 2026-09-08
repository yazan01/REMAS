"""AI analysis, improvement initiatives, roadmap and the final report.

Covers AI-01 → AI-07, FR-28 → FR-30 and BRD section 9, plus the layer gating of
FR-01 / section 10 — a Quick Score customer gets scoring and evidence review; the
AI narrative, initiatives, roadmap and PDF belong to the higher layers.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, get_assessment, get_current_user, require_ivalue
from app.core.config import settings
from app.core.errors import APIError
from app.core.security import utcnow
from app.db.session import get_db
from app.models import (
    AIFinding,
    AIJob,
    Assessment,
    AssessmentStatus,
    Initiative,
    ReportRender,
    RoadmapHorizon,
    ScoringRun,
    User,
)
from app.models.enums import IVALUE_ROLES
from app.services import audit, reporting
from app.services.ai import pipeline

router = APIRouter(tags=["insights"])
log = logging.getLogger("remas.insights")


def require_feature(assessment: Assessment, feature: str, user: User) -> None:
    """Layer gating. iValue staff bypass it so they can prepare a report before
    the customer's layer is upgraded."""
    if user.role in IVALUE_ROLES:
        return
    allowed = settings.layer_features.get(assessment.layer, [])
    if feature not in allowed:
        raise APIError(
            "layer.feature_not_included",
            status.HTTP_402_PAYMENT_REQUIRED,
            {"layer": assessment.layer, "feature": feature},
        )


def _require_submitted(assessment: Assessment, user: User) -> None:
    if assessment.status in (AssessmentStatus.DRAFT, AssessmentStatus.IN_PROGRESS):
        if user.role not in IVALUE_ROLES:
            raise APIError("assessment.not_submitted", status.HTTP_409_CONFLICT)


# ────────────────────────────── AI pipeline ────────────────────────────────


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
        require_feature(assessment, "ai_analysis", user)
    else:
        require_feature(assessment, "evidence_ai_review", user)
    _require_submitted(assessment, user)

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


# ─────────────────────── initiatives & roadmap ─────────────────────────────


class InitiativeIn(BaseModel):
    title_ar: str
    title_en: str
    axis_id: str | None = None
    objective_ar: str | None = None
    objective_en: str | None = None
    rationale_ar: str | None = None
    rationale_en: str | None = None
    owner_function_ar: str | None = None
    owner_function_en: str | None = None
    dependencies_ar: str | None = None
    dependencies_en: str | None = None
    horizon_code: str | None = None
    priority: int = Field(default=3, ge=1, le=5)
    linked_gap: str | None = None


class InitiativePatch(BaseModel):
    title_ar: str | None = None
    title_en: str | None = None
    objective_ar: str | None = None
    objective_en: str | None = None
    rationale_ar: str | None = None
    rationale_en: str | None = None
    owner_function_ar: str | None = None
    owner_function_en: str | None = None
    dependencies_ar: str | None = None
    dependencies_en: str | None = None
    horizon_code: str | None = None
    priority: int | None = Field(default=None, ge=1, le=5)
    order_index: int | None = None
    is_included: bool | None = None


def _initiative_dict(row: Initiative) -> dict:
    return {
        "id": row.id,
        "axis_id": row.axis_id,
        "title_ar": row.title_ar,
        "title_en": row.title_en,
        "objective_ar": row.objective_ar,
        "objective_en": row.objective_en,
        "rationale_ar": row.rationale_ar,
        "rationale_en": row.rationale_en,
        "owner_function_ar": row.owner_function_ar,
        "owner_function_en": row.owner_function_en,
        "dependencies_ar": row.dependencies_ar,
        "dependencies_en": row.dependencies_en,
        "linked_gap": row.linked_gap,
        "horizon_code": row.horizon_code,
        "priority": row.priority,
        "order_index": row.order_index,
        "source": row.source,
        "is_included": row.is_included,
    }


@router.get("/assessments/{assessment_id}/roadmap", response_model=dict)
def get_roadmap(
    assessment: Assessment = Depends(get_assessment),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """FR-28 / FR-29 — initiatives grouped into the configured horizons."""
    require_feature(assessment, "roadmap", user)
    horizons = list(
        db.scalars(
            select(RoadmapHorizon)
            .where(RoadmapHorizon.framework_version_id == assessment.framework_version_id)
            .order_by(RoadmapHorizon.order_index)
        )
    )
    initiatives = list(
        db.scalars(
            select(Initiative)
            .where(Initiative.assessment_id == assessment.id)
            .order_by(Initiative.priority, Initiative.order_index)
        )
    )
    return {
        "horizons": [
            {
                "code": h.code,
                "name_ar": h.name_ar,
                "name_en": h.name_en,
                "months_from": h.months_from,
                "months_to": h.months_to,
                "initiatives": [
                    _initiative_dict(i) for i in initiatives if i.horizon_code == h.code
                ],
            }
            for h in horizons
        ],
        "unassigned": [
            _initiative_dict(i)
            for i in initiatives
            if i.horizon_code not in {h.code for h in horizons}
        ],
        "total": len(initiatives),
    }


@router.post("/assessments/{assessment_id}/initiatives", response_model=dict, status_code=201)
def add_initiative(
    payload: InitiativeIn,
    request: Request,
    assessment: Assessment = Depends(get_assessment),
    user: User = Depends(require_ivalue),
    db: Session = Depends(get_db),
) -> dict:
    """FR-30 — a reviewer may add an initiative of their own."""
    count = len(
        db.scalars(select(Initiative).where(Initiative.assessment_id == assessment.id)).all()
    )
    initiative = Initiative(
        assessment_id=assessment.id,
        source="reviewer",
        order_index=count,
        edited_by_id=user.id,
        edited_at=utcnow(),
        **payload.model_dump(),
    )
    db.add(initiative)
    db.flush()
    audit.record(
        db, action="roadmap.initiative_added", entity_type="initiative",
        entity_id=initiative.id, actor=user, organization_id=assessment.organization_id,
        ip_address=client_ip(request),
    )
    db.commit()
    return _initiative_dict(initiative)


@router.patch("/initiatives/{initiative_id}", response_model=dict)
def update_initiative(
    initiative_id: str,
    payload: InitiativePatch,
    request: Request,
    user: User = Depends(require_ivalue),
    db: Session = Depends(get_db),
) -> dict:
    """FR-30 — remove, reprioritise or tailor before releasing the report."""
    initiative = db.get(Initiative, initiative_id)
    if initiative is None:
        raise APIError("roadmap.initiative_not_found", status.HTTP_404_NOT_FOUND)
    changes = payload.model_dump(exclude_none=True)
    for field, value in changes.items():
        setattr(initiative, field, value)
    initiative.edited_by_id = user.id
    initiative.edited_at = utcnow()
    audit.record(
        db, action="roadmap.initiative_updated", entity_type="initiative",
        entity_id=initiative.id, actor=user, payload={"fields": sorted(changes)},
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(initiative)
    return _initiative_dict(initiative)


@router.delete("/initiatives/{initiative_id}", status_code=204, response_model=None)
def delete_initiative(
    initiative_id: str,
    request: Request,
    user: User = Depends(require_ivalue),
    db: Session = Depends(get_db),
) -> None:
    initiative = db.get(Initiative, initiative_id)
    if initiative is None:
        raise APIError("roadmap.initiative_not_found", status.HTTP_404_NOT_FOUND)
    audit.record(
        db, action="roadmap.initiative_deleted", entity_type="initiative",
        entity_id=initiative.id, actor=user, payload={"title": initiative.title_en},
        ip_address=client_ip(request),
    )
    db.delete(initiative)
    db.commit()


# ──────────────────────────── final report ─────────────────────────────────


@router.get("/assessments/{assessment_id}/report.html", response_class=HTMLResponse)
def report_html(
    locale: str = Query(default="ar", pattern="^(ar|en)$"),
    assessment: Assessment = Depends(get_assessment),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    require_feature(assessment, "pdf_report", user)
    _require_submitted(assessment, user)
    ctx = reporting.build_context(db, assessment, locale)
    return HTMLResponse(reporting.render_html(ctx))


@router.get("/assessments/{assessment_id}/report.pdf")
def report_pdf(
    request: Request,
    locale: str = Query(default="ar", pattern="^(ar|en)$"),
    assessment: Assessment = Depends(get_assessment),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    """Branded PDF, printed through headless Chromium so Arabic shaping and RTL
    come out correct (BRD section 9)."""
    require_feature(assessment, "pdf_report", user)
    _require_submitted(assessment, user)

    ctx = reporting.build_context(db, assessment, locale)
    html_text = reporting.render_html(ctx)
    path = reporting.report_path(assessment.id, locale, "pdf")
    try:
        reporting.render_pdf(html_text, path)
    except Exception as exc:  # noqa: BLE001
        log.exception("PDF rendering failed")
        raise APIError(
            "report.render_failed", status.HTTP_500_INTERNAL_SERVER_ERROR,
            {"reason": type(exc).__name__},
        ) from exc

    run = db.scalars(
        select(ScoringRun)
        .where(ScoringRun.assessment_id == assessment.id)
        .order_by(ScoringRun.created_at.desc())
    ).first()
    render = ReportRender(
        assessment_id=assessment.id,
        scoring_run_id=run.id if run else None,
        locale=locale,
        fmt="pdf",
        layer=assessment.layer,
        stored_path=str(path),
        size_bytes=path.stat().st_size,
        generated_by_id=user.id,
    )
    db.add(render)
    audit.record(
        db, action="report.generated", entity_type="assessment", entity_id=assessment.id,
        actor=user, payload={"locale": locale, "size": render.size_bytes},
        ip_address=client_ip(request),
    )
    db.commit()

    filename = f"REMAS-{assessment.name}-{locale}.pdf".replace(" ", "_")
    return FileResponse(path, media_type="application/pdf", filename=filename)


@router.get("/assessments/{assessment_id}/report.json")
def report_json(
    locale: str = Query(default="ar", pattern="^(ar|en)$"),
    assessment: Assessment = Depends(get_assessment),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """The exportable structured data the BRD asks for alongside the PDF."""
    _require_submitted(assessment, user)
    ctx = reporting.build_context(db, assessment, locale)
    payload = reporting.structured_export(ctx)
    return Response(
        content=json.dumps(payload, ensure_ascii=False, indent=2),
        media_type="application/json; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="remas-{assessment.id}-{locale}.json"'
        },
    )


class ReleaseIn(BaseModel):
    locale: str = Field(default="ar", pattern="^(ar|en)$")


@router.post("/assessments/{assessment_id}/report/release", response_model=dict)
def release_report(
    payload: ReleaseIn,
    request: Request,
    assessment: Assessment = Depends(get_assessment),
    user: User = Depends(require_ivalue),
    db: Session = Depends(get_db),
) -> dict:
    """The iValue review-and-release gate from the BRD assumptions: the customer
    sees the final report only once a reviewer releases it."""
    ctx = reporting.build_context(db, assessment, payload.locale)
    path = reporting.report_path(assessment.id, payload.locale, "pdf")
    reporting.render_pdf(reporting.render_html(ctx), path)

    render = ReportRender(
        assessment_id=assessment.id,
        locale=payload.locale,
        fmt="pdf",
        layer=assessment.layer,
        stored_path=str(path),
        size_bytes=Path(path).stat().st_size,
        released=True,
        released_at=utcnow(),
        generated_by_id=user.id,
    )
    db.add(render)
    assessment.status = AssessmentStatus.COMPLETED
    audit.record(
        db, action="report.released", entity_type="assessment", entity_id=assessment.id,
        actor=user, payload={"locale": payload.locale}, ip_address=client_ip(request),
    )
    db.commit()
    return {"released": True, "locale": payload.locale, "assessment_status": assessment.status}


@router.get("/assessments/{assessment_id}/reports", response_model=list[dict])
def list_reports(
    assessment: Assessment = Depends(get_assessment), db: Session = Depends(get_db)
) -> list[dict]:
    rows = db.scalars(
        select(ReportRender)
        .where(ReportRender.assessment_id == assessment.id)
        .order_by(ReportRender.created_at.desc())
    )
    return [
        {
            "id": r.id,
            "locale": r.locale,
            "fmt": r.fmt,
            "released": r.released,
            "size_bytes": r.size_bytes,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/assessments/{assessment_id}/layer-features", response_model=dict)
def layer_features(assessment: Assessment = Depends(get_assessment)) -> dict:
    """What this assessment's service layer unlocks — drives which controls the
    UI offers rather than the UI guessing."""
    return {
        "layer": assessment.layer,
        "features": settings.layer_features.get(assessment.layer, []),
        "all_layers": settings.layer_features,
    }
