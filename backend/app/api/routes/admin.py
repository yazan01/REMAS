"""Administration portal API — BRD FR-31 → FR-35.

Everything an administrator needs to configure the platform *without a code
change*: frameworks, versions, axes, questions, weights, maturity levels,
scoring rules, roadmap horizons, the initiative library, report templates,
audit search, and bulk content import from iValue's master Excel file.

The version rule enforced throughout: a published version is immutable. Editing
means cloning to a new draft, changing that, and publishing it — which is what
keeps historical assessments reproducible (FR-35).
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import client_ip, require_ivalue
from app.core.errors import APIError
from app.core.security import utcnow
from app.db.session import get_db
from app.models import (
    Assessment,
    AuditLog,
    Axis,
    Framework,
    FrameworkStatus,
    FrameworkVersion,
    InitiativeTemplate,
    MaturityLevel,
    Organization,
    Question,
    RoadmapHorizon,
    User,
)
from app.models.content import DEFAULT_SCORING_CONFIG
from app.services import audit

router = APIRouter(prefix="/admin", tags=["admin"])
log = logging.getLogger("remas.admin")


def _editable(version: FrameworkVersion) -> FrameworkVersion:
    if version.status != FrameworkStatus.DRAFT:
        raise APIError("framework.version_locked", status.HTTP_409_CONFLICT)
    return version


def _load_version(db: Session, version_id: str) -> FrameworkVersion:
    version = db.get(FrameworkVersion, version_id)
    if version is None:
        raise APIError("framework.not_found", status.HTTP_404_NOT_FOUND)
    return version


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
    rows = db.scalars(select(Framework).order_by(Framework.created_at)).all()
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
    _seed_levels(db, version)
    _seed_horizons(db, version)
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
    version = _load_version(db, version_id)
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
    version = _editable(_load_version(db, version_id))
    config = dict(version.scoring_config or DEFAULT_SCORING_CONFIG)
    changes = payload.model_dump(exclude_none=True)
    if "formula" in changes and changes["formula"] not in ("weighted_average", "brd_literal"):
        raise APIError("scoring.unknown_formula", status.HTTP_422_UNPROCESSABLE_ENTITY)
    if "na_handling" in changes and changes["na_handling"] not in ("exclude", "zero"):
        raise APIError("scoring.unknown_na_handling", status.HTTP_422_UNPROCESSABLE_ENTITY)
    config.update(changes)
    version.scoring_config = config
    audit.record(
        db, action="admin.scoring_config_changed", entity_type="framework_version",
        entity_id=version.id, actor=user, payload={"changes": changes},
        ip_address=client_ip(request),
    )
    db.commit()
    return {"version_id": version.id, "scoring_config": config}


# ─────────────────────────── axes & questions ──────────────────────────────


class AxisIn(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    name_ar: str
    name_en: str
    description_ar: str | None = None
    description_en: str | None = None
    weight: float = Field(default=1.0, gt=0)
    order_index: int | None = None


class QuestionIn(BaseModel):
    code: str = Field(min_length=1, max_length=30)
    text_ar: str
    text_en: str
    guidance_ar: str | None = None
    guidance_en: str | None = None
    evidence_hint_ar: str | None = None
    evidence_hint_en: str | None = None
    weight: float = Field(default=1.0, gt=0)
    is_mandatory: bool = True
    evidence_required: bool = False
    allow_not_applicable: bool = True
    criteria: dict[str, Any] | None = None
    order_index: int | None = None


class LevelIn(BaseModel):
    score: int = Field(ge=1, le=10)
    label_ar: str
    label_en: str
    description_ar: str | None = None
    description_en: str | None = None


@router.post("/versions/{version_id}/axes", response_model=dict, status_code=201)
def create_axis(
    version_id: str,
    payload: AxisIn,
    request: Request,
    user: User = Depends(require_ivalue),
    db: Session = Depends(get_db),
) -> dict:
    version = _editable(_load_version(db, version_id))
    data = payload.model_dump()
    order = data.pop("order_index") or (len(version.axes) + 1)
    axis = Axis(framework_version_id=version.id, order_index=order, **data)
    db.add(axis)
    db.flush()
    audit.record(db, action="admin.axis_created", entity_type="axis", entity_id=axis.id,
                 actor=user, ip_address=client_ip(request))
    db.commit()
    return {"axis_id": axis.id, "code": axis.code}


@router.patch("/axes/{axis_id}", response_model=dict)
def update_axis(
    axis_id: str,
    payload: dict,
    request: Request,
    user: User = Depends(require_ivalue),
    db: Session = Depends(get_db),
) -> dict:
    axis = db.get(Axis, axis_id)
    if axis is None:
        raise APIError("framework.not_found", status.HTTP_404_NOT_FOUND)
    _editable(db.get(FrameworkVersion, axis.framework_version_id))
    for field in ("code", "name_ar", "name_en", "description_ar", "description_en",
                  "weight", "order_index"):
        if field in payload:
            setattr(axis, field, payload[field])
    audit.record(db, action="admin.axis_updated", entity_type="axis", entity_id=axis.id,
                 actor=user, payload={"fields": sorted(payload)}, ip_address=client_ip(request))
    db.commit()
    return {"axis_id": axis.id}


@router.delete("/axes/{axis_id}", status_code=204, response_model=None)
def delete_axis(
    axis_id: str,
    request: Request,
    user: User = Depends(require_ivalue),
    db: Session = Depends(get_db),
) -> None:
    axis = db.get(Axis, axis_id)
    if axis is None:
        raise APIError("framework.not_found", status.HTTP_404_NOT_FOUND)
    _editable(db.get(FrameworkVersion, axis.framework_version_id))
    audit.record(db, action="admin.axis_deleted", entity_type="axis", entity_id=axis.id,
                 actor=user, payload={"code": axis.code}, ip_address=client_ip(request))
    db.delete(axis)
    db.commit()


@router.post("/axes/{axis_id}/questions", response_model=dict, status_code=201)
def create_question(
    axis_id: str,
    payload: QuestionIn,
    request: Request,
    user: User = Depends(require_ivalue),
    db: Session = Depends(get_db),
) -> dict:
    axis = db.get(Axis, axis_id)
    if axis is None:
        raise APIError("framework.not_found", status.HTTP_404_NOT_FOUND)
    _editable(db.get(FrameworkVersion, axis.framework_version_id))
    data = payload.model_dump()
    order = data.pop("order_index") or (len(axis.questions) + 1)
    question = Question(axis_id=axis.id, order_index=order, **data)
    db.add(question)
    db.flush()
    audit.record(db, action="admin.question_created", entity_type="question",
                 entity_id=question.id, actor=user, ip_address=client_ip(request))
    db.commit()
    return {"question_id": question.id, "code": question.code}


@router.patch("/questions/{question_id}", response_model=dict)
def update_question(
    question_id: str,
    payload: dict,
    request: Request,
    user: User = Depends(require_ivalue),
    db: Session = Depends(get_db),
) -> dict:
    question = db.get(Question, question_id)
    if question is None:
        raise APIError("framework.not_found", status.HTTP_404_NOT_FOUND)
    axis = db.get(Axis, question.axis_id)
    _editable(db.get(FrameworkVersion, axis.framework_version_id))
    for field in ("code", "text_ar", "text_en", "guidance_ar", "guidance_en",
                  "evidence_hint_ar", "evidence_hint_en", "weight", "is_mandatory",
                  "evidence_required", "allow_not_applicable", "criteria", "order_index"):
        if field in payload:
            setattr(question, field, payload[field])
    audit.record(db, action="admin.question_updated", entity_type="question",
                 entity_id=question.id, actor=user, payload={"fields": sorted(payload)},
                 ip_address=client_ip(request))
    db.commit()
    return {"question_id": question.id}


@router.delete("/questions/{question_id}", status_code=204, response_model=None)
def delete_question(
    question_id: str,
    request: Request,
    user: User = Depends(require_ivalue),
    db: Session = Depends(get_db),
) -> None:
    question = db.get(Question, question_id)
    if question is None:
        raise APIError("framework.not_found", status.HTTP_404_NOT_FOUND)
    axis = db.get(Axis, question.axis_id)
    _editable(db.get(FrameworkVersion, axis.framework_version_id))
    audit.record(db, action="admin.question_deleted", entity_type="question",
                 entity_id=question.id, actor=user, payload={"code": question.code},
                 ip_address=client_ip(request))
    db.delete(question)
    db.commit()


@router.put("/versions/{version_id}/levels", response_model=list[dict])
def set_levels(
    version_id: str,
    payload: list[LevelIn],
    request: Request,
    user: User = Depends(require_ivalue),
    db: Session = Depends(get_db),
) -> list[dict]:
    version = _editable(_load_version(db, version_id))
    for existing in list(version.maturity_levels):
        db.delete(existing)
    db.flush()
    for level in payload:
        db.add(MaturityLevel(framework_version_id=version.id, **level.model_dump()))
    audit.record(db, action="admin.levels_updated", entity_type="framework_version",
                 entity_id=version.id, actor=user, ip_address=client_ip(request))
    db.commit()
    return [{"score": level.score, "label_ar": level.label_ar} for level in payload]


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


@router.put("/versions/{version_id}/horizons", response_model=list[dict])
def set_horizons(
    version_id: str,
    payload: list[HorizonIn],
    request: Request,
    user: User = Depends(require_ivalue),
    db: Session = Depends(get_db),
) -> list[dict]:
    """FR-29 — horizon labels and periods are configuration."""
    version = _load_version(db, version_id)
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
    _load_version(db, version_id)
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


# ───────────────────────────── content import ──────────────────────────────

IMPORT_COLUMNS = {
    "axis_code": ("axis_code", "axis", "pillar_code", "رمز المحور"),
    "axis_name_ar": ("axis_name_ar", "المحور", "اسم المحور"),
    "axis_name_en": ("axis_name_en", "axis_name", "pillar"),
    "axis_weight": ("axis_weight", "وزن المحور"),
    "question_code": ("question_code", "code", "رمز السؤال"),
    "text_ar": ("text_ar", "question_ar", "السؤال"),
    "text_en": ("text_en", "question_en", "question"),
    "guidance_ar": ("guidance_ar", "الإرشاد"),
    "guidance_en": ("guidance_en", "guidance"),
    "evidence_hint_ar": ("evidence_hint_ar", "الدليل", "المستند المطلوب"),
    "evidence_hint_en": ("evidence_hint_en", "evidence", "expected_document"),
    "weight": ("weight", "question_weight", "الوزن"),
    "is_mandatory": ("is_mandatory", "mandatory", "إلزامي"),
    "evidence_required": ("evidence_required", "requires_evidence", "دليل مطلوب"),
}


def _normalise_header(name: str) -> str | None:
    key = (name or "").strip().lower().replace(" ", "_")
    for field, aliases in IMPORT_COLUMNS.items():
        if key == field or key in aliases:
            return field
    return None


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "y", "نعم", "إلزامي", "مطلوب")


@router.post("/versions/{version_id}/import", response_model=dict)
async def import_content(
    version_id: str,
    request: Request,
    file: UploadFile = File(...),
    replace: bool = Query(default=True),
    user: User = Depends(require_ivalue),
    db: Session = Depends(get_db),
) -> dict:
    """Bulk-load iValue's master assessment content (FR-33).

    Accepts the master Excel file or a CSV with the same columns. Column names
    are matched in Arabic or English, so the sheet does not have to be rewritten
    to import it.
    """
    version = _editable(_load_version(db, version_id))
    raw = await file.read()
    name = (file.filename or "").lower()

    rows: list[dict[str, Any]] = []
    if name.endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        sheet = wb.worksheets[0]
        iterator = sheet.iter_rows(values_only=True)
        try:
            header = next(iterator)
        except StopIteration:
            raise APIError("import.empty_file", status.HTTP_422_UNPROCESSABLE_ENTITY) from None
        mapping = {i: _normalise_header(str(h or "")) for i, h in enumerate(header)}
        for values in iterator:
            row = {
                mapping[i]: values[i]
                for i in range(len(values))
                if i in mapping and mapping[i] and values[i] not in (None, "")
            }
            if row:
                rows.append(row)
        wb.close()
    elif name.endswith(".csv"):
        text = raw.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        for record in reader:
            row = {}
            for key, value in record.items():
                field = _normalise_header(key or "")
                if field and value not in (None, ""):
                    row[field] = value
            if row:
                rows.append(row)
    else:
        raise APIError("import.unsupported_format", status.HTTP_415_UNSUPPORTED_MEDIA_TYPE)

    if not rows:
        raise APIError("import.empty_file", status.HTTP_422_UNPROCESSABLE_ENTITY)

    if replace:
        for axis in list(version.axes):
            db.delete(axis)
        db.flush()

    axes_by_code: dict[str, Axis] = {a.code: a for a in version.axes}
    created_axes = 0
    created_questions = 0
    skipped: list[str] = []

    for index, row in enumerate(rows, start=2):
        axis_code = str(row.get("axis_code") or "").strip()
        if not axis_code:
            skipped.append(f"row {index}: missing axis_code")
            continue

        axis = axes_by_code.get(axis_code)
        if axis is None:
            axis = Axis(
                framework_version_id=version.id,
                code=axis_code,
                order_index=len(axes_by_code) + 1,
                name_ar=str(row.get("axis_name_ar") or axis_code),
                name_en=str(row.get("axis_name_en") or axis_code),
                weight=float(row.get("axis_weight") or 1.0),
            )
            db.add(axis)
            db.flush()
            axes_by_code[axis_code] = axis
            created_axes += 1

        question_code = str(row.get("question_code") or "").strip()
        text_ar = str(row.get("text_ar") or "").strip()
        text_en = str(row.get("text_en") or "").strip()
        if not question_code or not (text_ar or text_en):
            skipped.append(f"row {index}: missing question code or text")
            continue

        db.add(
            Question(
                axis_id=axis.id,
                code=question_code,
                order_index=len(axis.questions) + created_questions + 1,
                text_ar=text_ar or text_en,
                text_en=text_en or text_ar,
                guidance_ar=row.get("guidance_ar"),
                guidance_en=row.get("guidance_en"),
                evidence_hint_ar=row.get("evidence_hint_ar"),
                evidence_hint_en=row.get("evidence_hint_en"),
                weight=float(row.get("weight") or 1.0),
                is_mandatory=_truthy(row.get("is_mandatory", True)),
                evidence_required=_truthy(row.get("evidence_required", False)),
            )
        )
        created_questions += 1

    audit.record(
        db, action="admin.content_imported", entity_type="framework_version",
        entity_id=version.id, actor=user,
        payload={"file": file.filename, "axes": created_axes, "questions": created_questions,
                 "skipped": len(skipped)},
        ip_address=client_ip(request),
    )
    db.commit()
    return {
        "version_id": version.id,
        "axes_created": created_axes,
        "questions_created": created_questions,
        "skipped": skipped[:25],
        "skipped_count": len(skipped),
    }


@router.get("/import-template.csv", response_class=StreamingResponse)
def import_template(_u: User = Depends(require_ivalue)) -> StreamingResponse:
    """The exact column set the importer expects."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(list(IMPORT_COLUMNS.keys()))
    writer.writerow(
        ["AX01", "الحوكمة المؤسسية", "Corporate Governance", "1.2", "AX01-Q1",
         "هل يوجد ميثاق حوكمة معتمد؟", "Is there an approved governance charter?",
         "", "", "ميثاق الحوكمة", "Governance charter", "1.5", "yes", "yes"]
    )
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="remas-import-template.csv"'},
    )


# ────────────────────────── tenants & audit log ────────────────────────────


@router.get("/organizations", response_model=list[dict])
def list_organizations(
    _u: User = Depends(require_ivalue), db: Session = Depends(get_db)
) -> list[dict]:
    out = []
    for org in db.scalars(select(Organization).order_by(Organization.created_at)):
        assessments = db.scalars(
            select(Assessment).where(Assessment.organization_id == org.id)
        ).all()
        out.append(
            {
                "id": org.id,
                "slug": org.slug,
                "name_ar": org.name_ar,
                "name_en": org.name_en,
                "is_ivalue": org.is_ivalue,
                "is_active": org.is_active,
                "profile_completeness": org.profile_completeness,
                "user_count": len(org.users),
                "assessment_count": len(assessments),
                "created_at": org.created_at.isoformat(),
            }
        )
    return out


@router.patch("/organizations/{org_id}", response_model=dict)
def set_organization_active(
    org_id: str,
    payload: dict,
    request: Request,
    user: User = Depends(require_ivalue),
    db: Session = Depends(get_db),
) -> dict:
    org = db.get(Organization, org_id)
    if org is None:
        raise APIError("org.not_found", status.HTTP_404_NOT_FOUND)
    if "is_active" in payload:
        org.is_active = bool(payload["is_active"])
    audit.record(db, action="admin.organization_updated", entity_type="organization",
                 entity_id=org.id, actor=user, payload=payload, ip_address=client_ip(request))
    db.commit()
    return {"id": org.id, "is_active": org.is_active}


@router.get("/audit", response_model=dict)
def search_audit(
    q: str | None = Query(default=None, description="matches action, entity or actor email"),
    action: str | None = None,
    entity_type: str | None = None,
    organization_id: str | None = None,
    limit: int = Query(default=100, le=1000),
    offset: int = 0,
    _u: User = Depends(require_ivalue),
    db: Session = Depends(get_db),
) -> dict:
    """Searchable audit trail — the NFR requires it to be searchable and
    exportable, not merely written."""
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc())
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if organization_id:
        stmt = stmt.where(AuditLog.organization_id == organization_id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            AuditLog.action.like(like)
            | AuditLog.entity_type.like(like)
            | AuditLog.actor_email.like(like)
            | AuditLog.entity_id.like(like)
        )
    rows = list(db.scalars(stmt.offset(offset).limit(limit)))
    return {
        "count": len(rows),
        "offset": offset,
        "items": [
            {
                "id": row.id,
                "created_at": row.created_at.isoformat(),
                "actor_email": row.actor_email,
                "action": row.action,
                "entity_type": row.entity_type,
                "entity_id": row.entity_id,
                "organization_id": row.organization_id,
                "ip_address": row.ip_address,
                "payload": row.payload,
            }
            for row in rows
        ],
    }


@router.get("/audit/export.csv", response_class=StreamingResponse)
def export_audit(
    organization_id: str | None = None,
    _u: User = Depends(require_ivalue),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc())
    if organization_id:
        stmt = stmt.where(AuditLog.organization_id == organization_id)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["timestamp", "actor_email", "action", "entity_type", "entity_id",
         "organization_id", "ip_address", "payload"]
    )
    for row in db.scalars(stmt):
        writer.writerow(
            [row.created_at.isoformat(), row.actor_email or "", row.action, row.entity_type,
             row.entity_id or "", row.organization_id or "", row.ip_address or "",
             str(row.payload or "")]
        )
    buffer.seek(0)
    stamp = datetime.now().strftime("%Y%m%d")
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="remas-audit-{stamp}.csv"'},
    )


# ───────────────────────────── seed helpers ────────────────────────────────


def _seed_levels(db: Session, version: FrameworkVersion) -> None:
    defaults = [
        (1, "تأسيسي", "Initial"),
        (2, "ناشئ", "Developing"),
        (3, "مُعرَّف", "Defined"),
        (4, "مُدار", "Managed"),
        (5, "متميّز", "Distinguished"),
    ]
    for score, ar, en in defaults:
        db.add(
            MaturityLevel(
                framework_version_id=version.id, score=score, label_ar=ar, label_en=en
            )
        )


def _seed_horizons(db: Session, version: FrameworkVersion) -> None:
    defaults = [
        ("immediate", "أولويات فورية", "Immediate priorities", 0, 3),
        ("short", "المدى القصير", "Short term", 3, 6),
        ("medium", "المدى المتوسط", "Medium term", 6, 12),
        ("long", "المدى الطويل", "Long term", 12, 24),
    ]
    for index, (code, ar, en, start, end) in enumerate(defaults):
        db.add(
            RoadmapHorizon(
                framework_version_id=version.id, code=code, order_index=index,
                name_ar=ar, name_en=en, months_from=start, months_to=end,
            )
        )
