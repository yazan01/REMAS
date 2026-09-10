"""Customer organisations and the audit trail (FR-31, auditability NFR)."""

from __future__ import annotations

import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, require_ivalue
from app.core.errors import APIError
from app.db.session import get_db
from app.models import Assessment, AuditLog, Organization, User
from app.services import audit

router = APIRouter()

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
