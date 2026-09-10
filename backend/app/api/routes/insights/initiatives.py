"""Improvement initiatives and the phased roadmap — BRD FR-28 → FR-30.

The recommend stage of the pipeline proposes initiatives from iValue's library;
everything here is the editing surface over that proposal. Initiatives are
grouped into delivery horizons, so the roadmap is assembled from configured
horizons rather than hard-coded quarters.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, get_assessment, get_current_user, require_ivalue
from app.core.errors import APIError
from app.core.security import utcnow
from app.db.session import get_db
from app.models import Assessment, Initiative, RoadmapHorizon, User
from app.services import audit, entitlements

router = APIRouter(tags=["insights"])



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
    entitlements.require(assessment, entitlements.Feature.ROADMAP, user)
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

