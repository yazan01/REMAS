"""Account security and team management — the FR-03 / FR-04 gaps.

* password reset (request + confirm)
* TOTP multi-factor authentication — mandatory for administrator roles per the
  security NFR, so enrolment cannot be disabled once an admin has enabled it
* workspace invitations
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
    verify_password,
)
from app.db.session import get_db
from app.models import Invitation, Organization, User
from app.models.enums import IVALUE_ROLES, UserRole
from app.schemas import TokenOut, UserOut
from app.services import audit

router = APIRouter(prefix="/account", tags=["account"])
log = logging.getLogger("remas.account")

MFA_ISSUER = "REMAS"


# ─────────────────────────── password reset ────────────────────────────────


class ResetRequestIn(BaseModel):
    email: EmailStr


class ResetConfirmIn(BaseModel):
    token: str
    password: str = Field(min_length=8, max_length=128)


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


@router.post("/password/reset-request", status_code=status.HTTP_202_ACCEPTED)
def request_password_reset(
    payload: ResetRequestIn, request: Request, db: Session = Depends(get_db)
) -> dict:
    """Always returns 202. Confirming whether an address exists would turn this
    endpoint into an account-enumeration oracle."""
    user = db.scalar(select(User).where(func.lower(User.email) == payload.email.lower()))
    if user is not None:
        user.reset_token = new_token()
        user.reset_expires_at = utcnow() + timedelta(hours=2)
        audit.record(
            db,
            action="user.password_reset_requested",
            entity_type="user",
            entity_id=user.id,
            actor=user,
            ip_address=client_ip(request),
        )
        db.commit()
        # No mail transport yet; the token is logged so the flow is testable
        # — in development only, see log_delivery_token.
        log_delivery_token("password reset", user.email, user.reset_token)
    return {"status": "accepted"}


@router.get("/password/dev-token", include_in_schema=False)
def dev_reset_token(email: str, db: Session = Depends(get_db)) -> dict:
    if settings.environment != "development":
        raise APIError("auth.forbidden", status.HTTP_403_FORBIDDEN)
    user = db.scalar(select(User).where(func.lower(User.email) == email.lower()))
    if user is None:
        raise APIError("auth.invalid_token", status.HTTP_404_NOT_FOUND)
    return {"email": user.email, "token": user.reset_token}


@router.post("/password/reset", response_model=TokenOut)
def confirm_password_reset(
    payload: ResetConfirmIn, request: Request, db: Session = Depends(get_db)
) -> TokenOut:
    user = db.scalar(select(User).where(User.reset_token == payload.token))
    if user is None:
        raise APIError("auth.invalid_token", status.HTTP_400_BAD_REQUEST)
    expires = as_aware(user.reset_expires_at)
    if expires and expires < utcnow():
        raise APIError("auth.reset_expired", status.HTTP_400_BAD_REQUEST)

    user.password_hash = hash_password(payload.password)
    user.reset_token = None
    user.reset_expires_at = None
    if user.email_verified_at is None:
        # Holding the reset link proves control of the mailbox.
        user.email_verified_at = utcnow()

    audit.record(
        db,
        action="user.password_reset",
        entity_type="user",
        entity_id=user.id,
        actor=user,
        ip_address=client_ip(request),
    )
    db.commit()
    token = create_access_token(
        user.id, {"email": user.email, "role": user.role, "org": user.organization_id}
    )
    return TokenOut(access_token=token, expires_in=settings.access_token_minutes * 60)


@router.post("/password/change", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def change_password(
    payload: ChangePasswordIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    if not verify_password(payload.current_password, user.password_hash):
        raise APIError("auth.invalid_credentials", status.HTTP_401_UNAUTHORIZED)
    user.password_hash = hash_password(payload.new_password)
    audit.record(
        db,
        action="user.password_changed",
        entity_type="user",
        entity_id=user.id,
        actor=user,
        ip_address=client_ip(request),
    )
    db.commit()


# ──────────────────────────────── MFA ──────────────────────────────────────


class MfaEnrolOut(BaseModel):
    secret: str
    otpauth_uri: str
    already_enabled: bool


class MfaVerifyIn(BaseModel):
    code: str = Field(min_length=6, max_length=8)


@router.post("/mfa/enrol", response_model=MfaEnrolOut)
def enrol_mfa(
    request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> MfaEnrolOut:
    """Issues a TOTP secret. It is not active until a valid code confirms the
    authenticator app is in sync."""
    import pyotp

    if not user.mfa_secret or not user.mfa_enabled:
        user.mfa_secret = pyotp.random_base32()
        db.commit()

    uri = pyotp.TOTP(user.mfa_secret).provisioning_uri(name=user.email, issuer_name=MFA_ISSUER)
    audit.record(
        db,
        action="user.mfa_enrolment_started",
        entity_type="user",
        entity_id=user.id,
        actor=user,
        ip_address=client_ip(request),
    )
    db.commit()
    return MfaEnrolOut(
        secret=user.mfa_secret, otpauth_uri=uri, already_enabled=user.mfa_enabled
    )


@router.post("/mfa/confirm", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def confirm_mfa(
    payload: MfaVerifyIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    import pyotp

    if not user.mfa_secret:
        raise APIError("auth.mfa_not_enrolled", status.HTTP_400_BAD_REQUEST)
    if not pyotp.TOTP(user.mfa_secret).verify(payload.code, valid_window=1):
        raise APIError("auth.mfa_invalid", status.HTTP_401_UNAUTHORIZED)

    user.mfa_enabled = True
    audit.record(
        db,
        action="user.mfa_enabled",
        entity_type="user",
        entity_id=user.id,
        actor=user,
        ip_address=client_ip(request),
    )
    db.commit()


@router.delete("/mfa", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def disable_mfa(
    payload: MfaVerifyIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    import pyotp

    # The security NFR makes MFA mandatory for administrator roles, so an admin
    # cannot turn it back off.
    if user.role in IVALUE_ROLES:
        raise APIError("auth.mfa_required_for_role", status.HTTP_403_FORBIDDEN)
    if not user.mfa_secret or not pyotp.TOTP(user.mfa_secret).verify(payload.code, valid_window=1):
        raise APIError("auth.mfa_invalid", status.HTTP_401_UNAUTHORIZED)

    user.mfa_enabled = False
    user.mfa_secret = None
    audit.record(
        db,
        action="user.mfa_disabled",
        entity_type="user",
        entity_id=user.id,
        actor=user,
        ip_address=client_ip(request),
    )
    db.commit()


# ───────────────────────────── invitations ─────────────────────────────────


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
