"""The final report: HTML, PDF, structured export, and the release gate.

BRD section 9. Three representations of one document — the HTML the reviewer
reads in the browser, the branded PDF printed from that same HTML through
headless Chromium (the only engine that gets Arabic shaping and bidi ordering
right), and the structured JSON export that lets iValue feed the numbers
somewhere else.

`release` is the business gate, not a formatting step: the customer sees the
report only once an iValue reviewer has released it.
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

from app.api.deps import (
    client_ip,
    get_assessment,
    get_current_user,
    require_ivalue,
    require_submitted,
)
from app.core.errors import APIError
from app.core.security import utcnow
from app.db.session import get_db
from app.models import (
    Assessment,
    AssessmentStatus,
    ReportRender,
    ScoringRun,
    User,
)
from app.services import audit, entitlements, reporting

router = APIRouter(tags=["insights"])
log = logging.getLogger("remas.reports")



@router.get("/assessments/{assessment_id}/report.html", response_class=HTMLResponse)
def report_html(
    locale: str = Query(default="ar", pattern="^(ar|en)$"),
    assessment: Assessment = Depends(get_assessment),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    entitlements.require(assessment, entitlements.Feature.PDF_REPORT, user)
    require_submitted(assessment, user)
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
    entitlements.require(assessment, entitlements.Feature.PDF_REPORT, user)
    require_submitted(assessment, user)

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
    require_submitted(assessment, user)
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

