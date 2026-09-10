"""Delivery horizons and the initiative library (FR-29, AI-05).

The catalogue the recommendation stage draws on: what a horizon is called and
how long it spans, and which ready-made initiatives apply to which score band.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, require_ivalue
from app.core.errors import APIError
from app.db.session import get_db
from app.models import InitiativeTemplate, RoadmapHorizon, User
from app.services import audit, framework_service

router = APIRouter()

# ──────────────────── horizons & initiative library ────────────────────────


class HorizonIn(BaseModel):
    code: str
    name_ar: str
    name_en: str
    months_from: int = 0
    months_to: int = 3
    order_index: int = 0


class TemplateIn(BaseModel):
    code: str
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
    applies_min_score: float = 1.0
    applies_max_score: float = 5.0
    default_horizon_code: str | None = None
    effort: str | None = None


@router.get("/versions/{version_id}/horizons", response_model=list[dict])
def list_horizons(
    version_id: str, _u: User = Depends(require_ivalue), db: Session = Depends(get_db)
) -> list[dict]:
    """The editor needs to read the horizons before it can rewrite them; the PUT
    replaces the whole set, so it can't double as a fetch."""
    rows = db.scalars(
        select(RoadmapHorizon)
        .where(RoadmapHorizon.framework_version_id == version_id)
        .order_by(RoadmapHorizon.order_index)
    )
    return [
        {
            "code": h.code, "name_ar": h.name_ar, "name_en": h.name_en,
            "months_from": h.months_from, "months_to": h.months_to,
            "order_index": h.order_index,
        }
        for h in rows
    ]


@router.put("/versions/{version_id}/horizons", response_model=list[dict])
def set_horizons(
    version_id: str,
    payload: list[HorizonIn],
    request: Request,
    user: User = Depends(require_ivalue),
    db: Session = Depends(get_db),
) -> list[dict]:
    """FR-29 — horizon labels and periods are configuration."""
    version = framework_service.load_version(db, version_id)
    for existing in db.scalars(
        select(RoadmapHorizon).where(RoadmapHorizon.framework_version_id == version.id)
    ):
        db.delete(existing)
    db.flush()
    for index, horizon in enumerate(payload):
        data = horizon.model_dump()
        data["order_index"] = data.get("order_index") or index
        db.add(RoadmapHorizon(framework_version_id=version.id, **data))
    audit.record(db, action="admin.horizons_updated", entity_type="framework_version",
                 entity_id=version.id, actor=user, ip_address=client_ip(request))
    db.commit()
    return [h.model_dump() for h in payload]


@router.get("/versions/{version_id}/initiative-templates", response_model=list[dict])
def list_templates(
    version_id: str, _u: User = Depends(require_ivalue), db: Session = Depends(get_db)
) -> list[dict]:
    rows = db.scalars(
        select(InitiativeTemplate)
        .where(InitiativeTemplate.framework_version_id == version_id)
        .order_by(InitiativeTemplate.code)
    )
    return [
        {
            "id": t.id, "code": t.code, "axis_id": t.axis_id,
            "title_ar": t.title_ar, "title_en": t.title_en,
            "applies_min_score": t.applies_min_score, "applies_max_score": t.applies_max_score,
            "default_horizon_code": t.default_horizon_code, "is_active": t.is_active,
        }
        for t in rows
    ]


@router.post("/versions/{version_id}/initiative-templates", response_model=dict, status_code=201)
def create_template(
    version_id: str,
    payload: TemplateIn,
    request: Request,
    user: User = Depends(require_ivalue),
    db: Session = Depends(get_db),
) -> dict:
    framework_service.load_version(db, version_id)
    template = InitiativeTemplate(framework_version_id=version_id, **payload.model_dump())
    db.add(template)
    db.flush()
    audit.record(db, action="admin.initiative_template_created", entity_type="initiative_template",
                 entity_id=template.id, actor=user, ip_address=client_ip(request))
    db.commit()
    return {"id": template.id, "code": template.code}


@router.delete("/initiative-templates/{template_id}", status_code=204, response_model=None)
def delete_template(
    template_id: str,
    request: Request,
    user: User = Depends(require_ivalue),
    db: Session = Depends(get_db),
) -> None:
    template = db.get(InitiativeTemplate, template_id)
    if template is None:
        raise APIError("framework.not_found", status.HTTP_404_NOT_FOUND)
    audit.record(db, action="admin.initiative_template_deleted", entity_type="initiative_template",
                 entity_id=template.id, actor=user, ip_address=client_ip(request))
    db.delete(template)
    db.commit()
