from __future__ import annotations

import logging

import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings

log = logging.getLogger("remas.security")


def hash_password(raw: str) -> str:
    return bcrypt.hashpw(raw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(raw.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(subject: str, extra: dict | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload: dict = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_minutes),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None


def new_token(length: int = 32) -> str:
    return secrets.token_urlsafe(length)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_aware(value: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes even for timezone-aware columns.
    Normalise before any comparison so token expiry works on both SQLite and
    PostgreSQL."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def log_delivery_token(kind: str, recipient: str, token: str) -> None:
    """Log a single-use token so an e-mail flow can be completed without a mail
    server — in development only.

    The guard is the point. These tokens are bearer credentials: a
    password-reset token sitting in an aggregated production log is a full
    account takeover for anyone who can read that log, and log readership is
    almost always wider than database readership.

    Outside development the value is withheld and the event is still recorded,
    so an operator can see that a reset was requested without being handed the
    means to complete it.
    """
    if settings.environment == "development":
        log.info("%s token for %s: %s", kind, recipient, token)
    else:
        log.info("%s token issued for %s (value withheld)", kind, recipient)
