"""Assembling the data a report is rendered from.

The database-bound half of reporting: resolve which template applies, then
gather the assessment, its scoring run, the axis results, the AI findings and
the roadmap into one dictionary. Everything downstream of this module is pure.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import utcnow
from app.models import Assessment, FrameworkVersion, Organization, ScoringRun
from app.models.governance import ReportTemplate
from app.models.initiatives import AIFinding, Initiative, RoadmapHorizon
from app.services import assessment_service
from app.services.reporting.renderer import RAMP, T

log = logging.getLogger("remas.reporting")

def resolve_template(db: Session, assessment: Assessment) -> "ReportTemplate":
    """FR-34 - the template drives sections, branding, wording and formats.
    A version-specific default wins; otherwise the global default; otherwise a
    transient object carrying the shipped defaults."""
    from app.models import DEFAULT_BRANDING, DEFAULT_SECTIONS, ReportTemplate

    template = db.scalars(
        select(ReportTemplate)
        .where(
            ReportTemplate.framework_version_id == assessment.framework_version_id,
            ReportTemplate.is_active.is_(True),
        )
        .order_by(ReportTemplate.is_default.desc(), ReportTemplate.created_at)
    ).first()
    if template is None:
        template = db.scalars(
            select(ReportTemplate)
            .where(
                ReportTemplate.framework_version_id.is_(None),
                ReportTemplate.is_active.is_(True),
            )
            .order_by(ReportTemplate.is_default.desc(), ReportTemplate.created_at)
        ).first()
    if template is None:
        template = ReportTemplate(
            code="builtin",
            name_ar="القالب الافتراضي",
            name_en="Default template",
            sections=list(DEFAULT_SECTIONS),
            branding=dict(DEFAULT_BRANDING),
            copy_blocks={},
            output_formats=["pdf", "html", "json"],
            maturity_labels={},
            include_comparison=True,
        )
    return template


def build_context(db: Session, assessment: Assessment, locale: str = "ar") -> dict[str, Any]:
    org = db.get(Organization, assessment.organization_id)
    version = db.get(FrameworkVersion, assessment.framework_version_id)
    run = db.scalars(
        select(ScoringRun)
        .where(ScoringRun.assessment_id == assessment.id)
        .order_by(ScoringRun.created_at.desc())
    ).first()

    result = run.result if run and run.result else assessment_service.calculate(db, assessment).as_dict()
    axes = {a.id: a for a in assessment_service.selected_axes(db, assessment)}
    levels = {lv.score: lv for lv in (version.maturity_levels if version else [])}

    findings: dict[str, dict[str, list[AIFinding]]] = {}
    narrative: AIFinding | None = None
    for finding in db.scalars(
        select(AIFinding)
        .where(AIFinding.assessment_id == assessment.id, AIFinding.review_status != "rejected")
        .order_by(AIFinding.created_at.desc())
    ):
        if finding.kind == "narrative" and narrative is None:
            narrative = finding
        if finding.axis_id and finding.kind in ("strength", "gap", "opportunity"):
            bucket = findings.setdefault(finding.axis_id, {})
            bucket.setdefault(finding.kind, []).append(finding)

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
            .where(Initiative.assessment_id == assessment.id, Initiative.is_included.is_(True))
            .order_by(Initiative.priority, Initiative.order_index)
        )
    )

    template = resolve_template(db, assessment)
    from app.models import DEFAULT_BRANDING

    branding = {**DEFAULT_BRANDING, **(template.branding or {})}
    sections = {
        item["key"]: item
        for item in sorted(
            template.sections or [], key=lambda i: i.get("order", 0)
        )
    }
    # Template wording may override the framework's maturity labels (FR-34).
    for score, override in (template.maturity_labels or {}).items():
        level = levels.get(int(score))
        if level is not None and isinstance(override, dict):
            if override.get("ar"):
                level.label_ar = override["ar"]
            if override.get("en"):
                level.label_en = override["en"]

    comparison = (
        assessment_service.comparison(db, assessment)
        if template.include_comparison
        else None
    )

    return {
        "locale": locale,
        "t": T[locale],
        "org": org,
        "assessment": assessment,
        "version": version,
        "result": result,
        "axes": axes,
        "levels": levels,
        "findings": findings,
        "narrative": narrative,
        "horizons": horizons,
        "initiatives": initiatives,
        "template": template,
        "branding": branding,
        "sections": sections,
        "copy_blocks": template.copy_blocks or {},
        "comparison": comparison,
        "generated_at": utcnow(),
    }
