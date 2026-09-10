"""Workspace invitations and the member register — BRD FR-04.

An invitation is scoped to one organisation and carries the role the invitee
will hold, so accepting it is what creates the user — there is no window in
which an account exists inside a tenant without a role.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import can_manage_org, client_ip, get_current_user
from app.core.config import settings
from app.core.errors import APIError
from app.core.security import (
    as_aware,
    create_access_token,
    hash_password,
    log_delivery_token,
    new_token,
    utcnow,
)
from app.db.session import get_db
from app.models import Invitation, Organization, User
from app.models.enums import IVALUE_ROLES, UserRole
from app.schemas import TokenOut, UserOut
from app.services import audit

router = APIRouter()
log = logging.getLogger("remas.account")



class InviteIn(BaseModel):
    email: EmailStr
    role: UserRole = UserRole.CONTRIBUTOR


class InviteOut(BaseModel):
    id: str
    email: str
    role: str
    accepted: bool
    expires_at: str


class AcceptInviteIn(BaseModel):
    token: str
    full_name: str = Field(min_length=2, max_length=200)
    password: str = Field(min_length=8, max_length=128)


@router.get("/invitations", response_model=list[InviteOut])
def list_invitations(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[InviteOut]:
    if not can_manage_org(user):
        raise APIError("auth.forbidden", status.HTTP_403_FORBIDDEN)
    rows = db.scalars(
        select(Invitation)
        .where(Invitation.organization_id == user.organization_id)
        .order_by(Invitation.created_at.desc())
    )
    return [
        InviteOut(
            id=row.id,
            email=row.email,
            role=row.role,
            accepted=row.accepted_at is not None,
            expires_at=row.expires_at.isoformat(),
        )
        for row in rows
    ]


@router.post("/invitations", response_model=InviteOut, status_code=status.HTTP_201_CREATED)
def create_invitation(
    payload: InviteIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> InviteOut:
    if not can_manage_org(user):
        raise APIError("auth.forbidden", status.HTTP_403_FORBIDDEN)
    if payload.role in IVALUE_ROLES and user.role not in IVALUE_ROLES:
        # A customer admin must not be able to mint an iValue reviewer.
        raise APIError("auth.forbidden", status.HTTP_403_FORBIDDEN)
    if db.scalar(select(User).where(func.lower(User.email) == payload.email.lower())):
        raise APIError("auth.email_taken", status.HTTP_409_CONFLICT)

    invitation = Invitation(
        organization_id=user.organization_id,
        email=payload.email.lower(),
        role=payload.role,
        token=new_token(),
        expires_at=utcnow() + timedelta(days=14),
        invited_by_id=user.id,
    )
    db.add(invitation)
    db.flush()
    audit.record(
        db,
        action="user.invited",
        entity_type="invitation",
        entity_id=invitation.id,
        actor=user,
        payload={"email": invitation.email, "role": invitation.role},
        ip_address=client_ip(request),
    )
    db.commit()
    log_delivery_token("invitation", invitation.email, invitation.token)
    return InviteOut(
        id=invitation.id,
        email=invitation.email,
        role=invitation.role,
        accepted=False,
        expires_at=invitation.expires_at.isoformat(),
    )


@router.get("/invitations/dev-token", include_in_schema=False)
def dev_invite_token(email: str, db: Session = Depends(get_db)) -> dict:
    if settings.environment != "development":
        raise APIError("auth.forbidden", status.HTTP_403_FORBIDDEN)
    row = db.scalars(
        select(Invitation)
        .where(func.lower(Invitation.email) == email.lower())
        .order_by(Invitation.created_at.desc())
    ).first()
    if row is None:
        raise APIError("auth.invalid_token", status.HTTP_404_NOT_FOUND)
    return {"email": row.email, "token": row.token}


@router.post("/invitations/accept", response_model=TokenOut)
def accept_invitation(
    payload: AcceptInviteIn, request: Request, db: Session = Depends(get_db)
) -> TokenOut:
    invitation = db.scalar(select(Invitation).where(Invitation.token == payload.token))
    if invitation is None or invitation.accepted_at is not None:
        raise APIError("auth.invalid_token", status.HTTP_400_BAD_REQUEST)
    expires = as_aware(invitation.expires_at)
    if expires and expires < utcnow():
        raise APIError("auth.invite_expired", status.HTTP_400_BAD_REQUEST)
    if db.scalar(select(User).where(func.lower(User.email) == invitation.email)):
        raise APIError("auth.email_taken", status.HTTP_409_CONFLICT)

    org = db.get(Organization, invitation.organization_id)
    if org is None:
        raise APIError("org.not_found", status.HTTP_404_NOT_FOUND)

    user = User(
        organization_id=org.id,
        email=invitation.email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        role=invitation.role,
        email_verified_at=utcnow(),  # the invite link proves mailbox control
    )
    db.add(user)
    invitation.accepted_at = utcnow()
    db.flush()
    audit.record(
        db,
        action="user.invitation_accepted",
        entity_type="user",
        entity_id=user.id,
        actor=user,
        organization_id=org.id,
        ip_address=client_ip(request),
    )
    db.commit()
    token = create_access_token(
        user.id, {"email": user.email, "role": user.role, "org": user.organization_id}
    )
    return TokenOut(access_token=token, expires_in=settings.access_token_minutes * 60)


@router.get("/members", response_model=list[UserOut])
def list_members(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[User]:
    return list(
        db.scalars(
            select(User)
            .where(User.organization_id == user.organization_id)
            .order_by(User.created_at)
        )
    )
