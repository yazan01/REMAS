"""The user register across every tenant (FR-31).

Reading is open to iValue staff; changing a role or suspending an account is
administrator-only, which is why this module uses two different guards.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, require_ivalue, require_ivalue_admin
from app.core.errors import APIError
from app.db.session import get_db
from app.models import Organization, User
from app.models.enums import UserRole
from app.services import audit

router = APIRouter()

# ─────────────────────── users across every tenant ──────────────────────────


class UserPatch(BaseModel):
    role: str | None = None
    is_active: bool | None = None


@router.get("/users", response_model=dict)
def list_users(
    q: str | None = Query(default=None, description="matches name or email"),
    organization_id: str | None = None,
    role: str | None = None,
    limit: int = Query(default=200, le=1000),
    offset: int = 0,
    _u: User = Depends(require_ivalue),
    db: Session = Depends(get_db),
) -> dict:
    """Every user on the platform, across tenants.

    The per-organisation view lives in the customer's own workspace; this is the
    iValue-side register the administration portal needs (FR-31).
    """
    stmt = select(User).order_by(User.created_at.desc())
    if organization_id:
        stmt = stmt.where(User.organization_id == organization_id)
    if role:
        stmt = stmt.where(User.role == role)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(User.full_name.like(like) | User.email.like(like))

    rows = list(db.scalars(stmt.offset(offset).limit(limit)))
    orgs = {
        org.id: org
        for org in db.scalars(select(Organization))
    }
    return {
        "count": len(rows),
        "offset": offset,
        "roles": [str(r) for r in UserRole],
        "items": [
            {
                "id": user.id,
                "email": user.email,
                "full_name": user.full_name,
                "role": user.role,
                "is_active": user.is_active,
                "mfa_enabled": user.mfa_enabled,
                "email_verified": user.email_verified_at is not None,
                "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
                "created_at": user.created_at.isoformat(),
                "organization_id": user.organization_id,
                "organization_name_ar": orgs[user.organization_id].name_ar
                if user.organization_id in orgs
                else None,
                "organization_name_en": orgs[user.organization_id].name_en
                if user.organization_id in orgs
                else None,
            }
            for user in rows
        ],
    }


@router.patch("/users/{user_id}", response_model=dict)
def update_user(
    user_id: str,
    payload: UserPatch,
    request: Request,
    actor: User = Depends(require_ivalue_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Change a role or suspend an account. Administrator only — a reviewer can
    read the register but not rewrite who has access to what."""
    target = db.get(User, user_id)
    if target is None:
        raise APIError("auth.user_not_found", status.HTTP_404_NOT_FOUND)

    changes = payload.model_dump(exclude_none=True)
    if "role" in changes:
        valid = {str(r) for r in UserRole}
        if changes["role"] not in valid:
            raise APIError(
                "auth.unknown_role", status.HTTP_422_UNPROCESSABLE_CONTENT,
                {"valid": sorted(valid)},
            )
    if target.id == actor.id:
        # Locking yourself out, or demoting the last administrator, leaves the
        # platform with nobody who can undo it.
        if changes.get("is_active") is False or (
            "role" in changes and changes["role"] != UserRole.IVALUE_ADMIN
        ):
            raise APIError("auth.cannot_demote_self", status.HTTP_409_CONFLICT)

    if changes.get("role") and target.role == UserRole.IVALUE_ADMIN:
        remaining = db.scalars(
            select(User).where(
                User.role == UserRole.IVALUE_ADMIN,
                User.is_active.is_(True),
                User.id != target.id,
            )
        ).first()
        if remaining is None and changes["role"] != UserRole.IVALUE_ADMIN:
            raise APIError("auth.last_admin", status.HTTP_409_CONFLICT)

    previous = {"role": target.role, "is_active": target.is_active}
    for field, value in changes.items():
        setattr(target, field, value)

    audit.record(
        db, action="admin.user_updated", entity_type="user", entity_id=target.id,
        actor=actor, organization_id=target.organization_id,
        payload={"from": previous, "to": changes},
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(target)
    return {
        "id": target.id,
        "email": target.email,
        "role": target.role,
        "is_active": target.is_active,
    }
