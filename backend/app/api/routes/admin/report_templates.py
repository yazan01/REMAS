"""Configurable report templates — BRD FR-34.

Sections, branding, copy blocks, output formats and the maturity-label wording
that the final report is rendered through. This is administration data: it is
authored once by iValue and applies to every tenant's report, which is why it
belongs beside the other `/admin` configuration rather than beside a customer's
assessment.

The `/admin` prefix is supplied by the package router in `admin/__init__.py`,
so the paths below are written without it.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, require_ivalue
from app.core.errors import APIError
from app.db.session import get_db
from app.models import (
    DEFAULT_BRANDING,
    DEFAULT_SECTIONS,
    REPORT_SECTIONS,
    ReportTemplate,
    User,
)
from app.services import audit

router = APIRouter()

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


@router.get("/report-templates", response_model=dict)
def list_templates(
    _u: User = Depends(require_ivalue), db: Session = Depends(get_db)
) -> dict:
    rows = db.scalars(select(ReportTemplate).order_by(ReportTemplate.created_at))
    return {
        "templates": [_template_dict(r) for r in rows],
        "available_sections": REPORT_SECTIONS,
        "defaults": {"sections": DEFAULT_SECTIONS, "branding": DEFAULT_BRANDING},
    }


@router.post("/report-templates", response_model=dict, status_code=201)
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


@router.patch("/report-templates/{template_id}", response_model=dict)
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
    "/report-templates/{template_id}",
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


