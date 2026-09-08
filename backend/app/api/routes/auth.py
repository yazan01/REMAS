from __future__ import annotations

import logging
import re
from datetime import timedelta

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, get_current_user
from app.core.config import settings
from app.core.errors import APIError
from app.core.security import (
    as_aware,
    create_access_token,
    hash_password,
    new_token,
    utcnow,
    verify_password,
)
from app.db.session import get_db
from app.models import Organization, User
from app.models.enums import UserRole
from app.schemas import LoginIn, MeOut, RegisterIn, TokenOut, UserOut, VerifyIn
from app.services import audit

router = APIRouter(prefix="/auth", tags=["auth"])
log = logging.getLogger("remas.auth")


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9؀-ۿ]+", "-", value).strip("-").lower()
    return slug[:60] or "org"


def _unique_slug(db: Session, base: str) -> str:
    slug = _slugify(base)
    candidate = slug
    n = 2
    while db.scalar(select(func.count()).select_from(Organization).where(Organization.slug == candidate)):
        candidate = f"{slug}-{n}"
        n += 1
    return candidate


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterIn, request: Request, db: Session = Depends(get_db)) -> User:
    email = payload.email.lower()
    exists = db.scalar(select(User).where(func.lower(User.email) == email))
    if exists:
        raise APIError("auth.email_taken", status.HTTP_409_CONFLICT)

    org = Organization(
        slug=_unique_slug(db, payload.organization_name_en),
        name_ar=payload.organization_name_ar,
        name_en=payload.organization_name_en,
    )
    db.add(org)
    db.flush()

    user = User(
        organization_id=org.id,
        email=email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        role=UserRole.ORG_OWNER,
        locale=payload.locale,
        verification_token=new_token(),
        verification_expires_at=utcnow() + timedelta(hours=settings.verification_token_hours),
    )
    db.add(user)
    db.flush()

    audit.record(
        db,
        action="user.registered",
        entity_type="user",
        entity_id=user.id,
        actor=user,
        organization_id=org.id,
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(user)

    # No mail transport is wired yet; the link is logged so the flow is testable
    # end to end in development.
    log.info("verification token for %s: %s", user.email, user.verification_token)
    return user


@router.post("/verify", response_model=TokenOut)
def verify_email(payload: VerifyIn, request: Request, db: Session = Depends(get_db)) -> TokenOut:
    user = db.scalar(select(User).where(User.verification_token == payload.token))
    if user is None:
        raise APIError("auth.invalid_token", status.HTTP_400_BAD_REQUEST)
    expires_at = as_aware(user.verification_expires_at)
    if expires_at and expires_at < utcnow():
        raise APIError("auth.invalid_token", status.HTTP_400_BAD_REQUEST)

    user.email_verified_at = utcnow()
    user.verification_token = None
    user.verification_expires_at = None
    audit.record(
        db,
        action="user.email_verified",
        entity_type="user",
        entity_id=user.id,
        actor=user,
        ip_address=client_ip(request),
    )
    db.commit()
    return _issue_token(user)


@router.get("/dev/verification-token", include_in_schema=False)
def dev_verification_token(email: str, db: Session = Depends(get_db)) -> dict:
    """Development helper so the sign-up flow can be completed without a mail
    server. Disabled outside development."""
    if settings.environment != "development":
        raise APIError("auth.forbidden", status.HTTP_403_FORBIDDEN)
    user = db.scalar(select(User).where(func.lower(User.email) == email.lower()))
    if user is None:
        raise APIError("auth.invalid_token", status.HTTP_404_NOT_FOUND)
    return {"email": user.email, "token": user.verification_token}


@router.post("/login", response_model=TokenOut)
def login(payload: LoginIn, request: Request, db: Session = Depends(get_db)) -> TokenOut:
    user = db.scalar(select(User).where(func.lower(User.email) == payload.email.lower()))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise APIError("auth.invalid_credentials", status.HTTP_401_UNAUTHORIZED)
    if not user.is_active:
        raise APIError("auth.account_disabled", status.HTTP_403_FORBIDDEN)
    if user.email_verified_at is None:
        raise APIError("auth.email_not_verified", status.HTTP_403_FORBIDDEN)

    user.last_login_at = utcnow()
    audit.record(
        db,
        action="user.login",
        entity_type="user",
        entity_id=user.id,
        actor=user,
        ip_address=client_ip(request),
    )
    db.commit()
    return _issue_token(user)


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> MeOut:
    org = db.get(Organization, user.organization_id)
    if org is None:
        raise APIError("org.not_found", status.HTTP_404_NOT_FOUND)
    return MeOut(
        user=UserOut.model_validate(user),
        organization_name_ar=org.name_ar,
        organization_name_en=org.name_en,
        organization_slug=org.slug,
        profile_completeness=org.profile_completeness,
    )


@router.patch("/me/locale", response_model=UserOut)
def set_locale(
    locale: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """Persist the language chosen with the header toggle, so the next sign-in
    on any device opens in the same language."""
    if locale not in ("ar", "en"):
        raise APIError("validation.failed", status.HTTP_422_UNPROCESSABLE_ENTITY)
    user.locale = locale
    db.commit()
    db.refresh(user)
    return user


def _issue_token(user: User) -> TokenOut:
    token = create_access_token(
        user.id, {"email": user.email, "role": user.role, "org": user.organization_id}
    )
    return TokenOut(access_token=token, expires_in=settings.access_token_minutes * 60)
