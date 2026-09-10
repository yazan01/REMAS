"""Password reset and password change — BRD FR-03.

The reset token is a bearer credential: whoever holds it owns the account until
it is used. It is single-use, time-boxed, and its value is only ever written to
the log in development (`log_delivery_token`), because production log
readership is almost always wider than database readership.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, get_current_user
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
from app.models import User
from app.schemas import TokenOut
from app.services import audit

router = APIRouter()
log = logging.getLogger("remas.account")



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


