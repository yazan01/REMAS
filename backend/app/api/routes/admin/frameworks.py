"""Frameworks, versions and the scoring configuration (FR-32, FR-35).

Creating a tool, cloning a version to a draft, publishing it, and changing the
rules the engine calculates with. The lifecycle rules themselves live in
`services/framework_service.py`; this module is the HTTP surface over them.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import client_ip, require_ivalue
from app.core.errors import APIError
from app.core.security import utcnow
from app.db.session import get_db
from app.models import (
    Axis,
    Framework,
    FrameworkStatus,
    FrameworkVersion,
    InitiativeTemplate,
    MaturityLevel,
    Question,
    RoadmapHorizon,
    User,
)
from app.models.content import DEFAULT_SCORING_CONFIG
from app.services import audit, framework_service

router = APIRouter()

# ───────────────────────── frameworks & versions ───────────────────────────


class FrameworkIn(BaseModel):
    code: str = Field(min_length=2, max_length=40)
    name_ar: str
    name_en: str
    description_ar: str | None = None
    description_en: str | None = None


class VersionIn(BaseModel):
    version: str = Field(min_length=1, max_length=20)
    source_note: str | None = None
    scoring_config: dict[str, Any] | None = None


class ScoringConfigIn(BaseModel):
    formula: str | None = None
    na_handling: str | None = None
    min_axis_coverage: float | None = Field(default=None, ge=0, le=1)
    strength_threshold: float | None = None
    gap_threshold: float | None = None
    thresholds: list[dict[str, Any]] | None = None
    priority_weights: dict[str, float] | None = None


@router.get("/frameworks", response_model=list[dict])
def list_frameworks(_u: User = Depends(require_ivalue), db: Session = Depends(get_db)) -> list[dict]:
    """Every framework with its versions and their content counts.

    The counts are what made this expensive: `len(v.axes)` and
    `sum(len(a.questions) for a in v.axes)` each triggered a lazy load, so the
    call cost one query per version plus one per axis — 20 queries for a single
    16-axis framework, growing with every axis an administrator adds. Loading
    the whole chain eagerly turns that into a fixed three.
    """
    rows = db.scalars(
        select(Framework)
        .order_by(Framework.created_at)
        .options(
            selectinload(Framework.versions)
            .selectinload(FrameworkVersion.axes)
            .selectinload(Axis.questions)
        )
    ).all()
    out = []
    for framework in rows:
        out.append(
            {
                "id": framework.id,
                "code": framework.code,
                "name_ar": framework.name_ar,
                "name_en": framework.name_en,
                "is_active": framework.is_active,
                "versions": [
                    {
                        "id": v.id,
                        "version": v.version,
                        "status": v.status,
                        "published_at": v.published_at.isoformat() if v.published_at else None,
                        "axis_count": len(v.axes),
                        "question_count": sum(len(a.questions) for a in v.axes),
                    }
                    for v in sorted(framework.versions, key=lambda v: v.created_at)
                ],
            }
        )
    return out


@router.post("/frameworks", response_model=dict, status_code=status.HTTP_201_CREATED)
def create_framework(
    payload: FrameworkIn,
    request: Request,
    user: User = Depends(require_ivalue),
    db: Session = Depends(get_db),
) -> dict:
    """FR-32 — multiple assessment tools, created through configuration."""
    if db.scalar(select(Framework).where(Framework.code == payload.code)):
        raise APIError("framework.code_taken", status.HTTP_409_CONFLICT)
    framework = Framework(**payload.model_dump())
    db.add(framework)
    db.flush()
    version = FrameworkVersion(
        framework_id=framework.id,
        version="0.1-draft",
        status=FrameworkStatus.DRAFT,
        scoring_config=dict(DEFAULT_SCORING_CONFIG),
    )
    db.add(version)
    db.flush()
    framework_service.seed_default_levels(db, version)
    framework_service.seed_default_horizons(db, version)
    audit.record(
        db, action="admin.framework_created", entity_type="framework",
        entity_id=framework.id, actor=user, ip_address=client_ip(request),
    )
    db.commit()
    return {"framework_id": framework.id, "draft_version_id": version.id}


@router.patch("/frameworks/{framework_id}", response_model=dict)
def update_framework(
    framework_id: str,
    payload: dict,
    request: Request,
    user: User = Depends(require_ivalue),
    db: Session = Depends(get_db),
) -> dict:
    framework = db.get(Framework, framework_id)
    if framework is None:
        raise APIError("framework.not_found", status.HTTP_404_NOT_FOUND)
    for field in ("name_ar", "name_en", "description_ar", "description_en", "is_active"):
        if field in payload:
            setattr(framework, field, payload[field])
    audit.record(
        db, action="admin.framework_updated", entity_type="framework",
        entity_id=framework.id, actor=user, payload={"fields": sorted(payload)},
        ip_address=client_ip(request),
    )
    db.commit()
    return {"id": framework.id, "is_active": framework.is_active}


@router.post("/versions/{version_id}/clone", response_model=dict, status_code=201)
def clone_version(
    version_id: str,
    payload: VersionIn,
    request: Request,
    user: User = Depends(require_ivalue),
    db: Session = Depends(get_db),
) -> dict:
    """The only way to change published content: clone it into a new draft
    (FR-35). Historical assessments stay bound to the version they used."""
    source = db.get(
        FrameworkVersion,
        version_id,
        options=[
            selectinload(FrameworkVersion.axes).selectinload(Axis.questions),
            selectinload(FrameworkVersion.maturity_levels),
        ],
    )
    if source is None:
        raise APIError("framework.not_found", status.HTTP_404_NOT_FOUND)
    if db.scalar(
        select(FrameworkVersion).where(
            FrameworkVersion.framework_id == source.framework_id,
            FrameworkVersion.version == payload.version,
        )
    ):
        raise APIError("framework.version_taken", status.HTTP_409_CONFLICT)

    clone = FrameworkVersion(
        framework_id=source.framework_id,
        version=payload.version,
        status=FrameworkStatus.DRAFT,
        scoring_config=payload.scoring_config or dict(source.scoring_config),
        source_note=payload.source_note or f"cloned from {source.version}",
    )
    db.add(clone)
    db.flush()

    for level in source.maturity_levels:
        db.add(
            MaturityLevel(
                framework_version_id=clone.id,
                score=level.score,
                label_ar=level.label_ar,
                label_en=level.label_en,
                description_ar=level.description_ar,
                description_en=level.description_en,
            )
        )
    for axis in source.axes:
        new_axis = Axis(
            framework_version_id=clone.id,
            code=axis.code,
            order_index=axis.order_index,
            name_ar=axis.name_ar,
            name_en=axis.name_en,
            description_ar=axis.description_ar,
            description_en=axis.description_en,
            weight=axis.weight,
        )
        db.add(new_axis)
        db.flush()
        for question in axis.questions:
            db.add(
                Question(
                    axis_id=new_axis.id,
                    code=question.code,
                    order_index=question.order_index,
                    text_ar=question.text_ar,
                    text_en=question.text_en,
                    guidance_ar=question.guidance_ar,
                    guidance_en=question.guidance_en,
                    evidence_hint_ar=question.evidence_hint_ar,
                    evidence_hint_en=question.evidence_hint_en,
                    weight=question.weight,
                    is_mandatory=question.is_mandatory,
                    evidence_required=question.evidence_required,
                    allow_not_applicable=question.allow_not_applicable,
                    response_type=question.response_type,
                    criteria=question.criteria,
                )
            )
    for horizon in db.scalars(
        select(RoadmapHorizon).where(RoadmapHorizon.framework_version_id == source.id)
    ):
        db.add(
            RoadmapHorizon(
                framework_version_id=clone.id,
                code=horizon.code,
                order_index=horizon.order_index,
                name_ar=horizon.name_ar,
                name_en=horizon.name_en,
                months_from=horizon.months_from,
                months_to=horizon.months_to,
            )
        )
    for template in db.scalars(
        select(InitiativeTemplate).where(InitiativeTemplate.framework_version_id == source.id)
    ):
        db.add(
            InitiativeTemplate(
                framework_version_id=clone.id,
                axis_id=None,
                code=template.code,
                title_ar=template.title_ar,
                title_en=template.title_en,
                objective_ar=template.objective_ar,
                objective_en=template.objective_en,
                rationale_ar=template.rationale_ar,
                rationale_en=template.rationale_en,
                owner_function_ar=template.owner_function_ar,
                owner_function_en=template.owner_function_en,
                dependencies_ar=template.dependencies_ar,
                dependencies_en=template.dependencies_en,
                applies_min_score=template.applies_min_score,
                applies_max_score=template.applies_max_score,
                default_horizon_code=template.default_horizon_code,
                effort=template.effort,
            )
        )

    audit.record(
        db, action="admin.version_cloned", entity_type="framework_version",
        entity_id=clone.id, actor=user, payload={"from": source.id, "version": clone.version},
        ip_address=client_ip(request),
    )
    db.commit()
    return {"version_id": clone.id, "version": clone.version, "status": clone.status}


@router.post("/versions/{version_id}/publish", response_model=dict)
def publish_version(
    version_id: str,
    request: Request,
    user: User = Depends(require_ivalue),
    db: Session = Depends(get_db),
) -> dict:
    version = framework_service.load_version(db, version_id)
    if version.status == FrameworkStatus.PUBLISHED:
        return {"version_id": version.id, "status": version.status}
    if not version.axes:
        raise APIError("framework.empty_version", status.HTTP_409_CONFLICT)

    # Only one live version per framework.
    for other in db.scalars(
        select(FrameworkVersion).where(
            FrameworkVersion.framework_id == version.framework_id,
            FrameworkVersion.status == FrameworkStatus.PUBLISHED,
        )
    ):
        other.status = FrameworkStatus.ARCHIVED

    version.status = FrameworkStatus.PUBLISHED
    version.published_at = utcnow()
    audit.record(
        db, action="admin.version_published", entity_type="framework_version",
        entity_id=version.id, actor=user, payload={"version": version.version},
        ip_address=client_ip(request),
    )
    db.commit()
    return {"version_id": version.id, "status": version.status}


@router.patch("/versions/{version_id}/scoring", response_model=dict)
def update_scoring_config(
    version_id: str,
    payload: ScoringConfigIn,
    request: Request,
    user: User = Depends(require_ivalue),
    db: Session = Depends(get_db),
) -> dict:
    """FR-33 / FR-26 — scoring rules are configuration, and changing them is an
    audited administrative act, never something the AI can do."""
    version = framework_service.assert_editable(framework_service.load_version(db, version_id))
    config = dict(version.scoring_config or DEFAULT_SCORING_CONFIG)
    changes = payload.model_dump(exclude_none=True)
    if "formula" in changes and changes["formula"] not in ("weighted_average", "brd_literal"):
        raise APIError("scoring.unknown_formula", status.HTTP_422_UNPROCESSABLE_CONTENT)
    if "na_handling" in changes and changes["na_handling"] not in ("exclude", "zero"):
        raise APIError("scoring.unknown_na_handling", status.HTTP_422_UNPROCESSABLE_CONTENT)
    config.update(changes)
    version.scoring_config = config
    audit.record(
        db, action="admin.scoring_config_changed", entity_type="framework_version",
        entity_id=version.id, actor=user, payload={"changes": changes},
        ip_address=client_ip(request),
    )
    db.commit()
    return {"version_id": version.id, "scoring_config": config}
