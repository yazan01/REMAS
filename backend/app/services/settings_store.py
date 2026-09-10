"""Read/write access to the administrator-configurable platform settings.

Environment variables stay the floor: whatever the deployment sets is used until
an administrator overrides it from the portal. That ordering matters because a
container can be handed a key through a secret mount with no database write, and
a portal change must not be lost on the next restart either.

A short in-process cache keeps the AI and OCR paths from issuing a query per
call; every write clears it, so the portal reflects a change immediately.
"""

from __future__ import annotations

import logging
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto import decrypt, encrypt
from app.models.settings import PLATFORM_SCOPE, PlatformSetting

log = logging.getLogger("remas.settings")

CACHE_SECONDS = 15.0

_cache: dict[str, str | None] = {}
_cache_at: float = 0.0


def invalidate() -> None:
    global _cache_at
    _cache_at = 0.0


def _seal(plaintext: str) -> bytes:
    master = settings.evidence_master_key
    if not master:
        # Refusing is safer than writing a key in the clear and calling it
        # stored; the caller surfaces this to the administrator.
        raise RuntimeError("no_master_key")
    return encrypt(plaintext.encode("utf-8"), master, PLATFORM_SCOPE)


def _open(blob: bytes) -> str | None:
    master = settings.evidence_master_key
    if not master:
        return None
    try:
        return decrypt(blob, master, PLATFORM_SCOPE).decode("utf-8")
    except Exception as exc:  # noqa: BLE001 - a rotated master key must not 500
        log.warning("platform secret could not be opened: %s", type(exc).__name__)
        return None


def all_values(db: Session) -> dict[str, str | None]:
    """Every stored setting, secrets decrypted, cached briefly."""
    global _cache, _cache_at
    now = time.monotonic()
    if _cache_at and now - _cache_at < CACHE_SECONDS:
        return _cache

    out: dict[str, str | None] = {}
    for row in db.scalars(select(PlatformSetting)):
        out[row.key] = _open(row.secret) if row.secret else row.value
    _cache, _cache_at = out, now
    return out


def get(db: Session, key: str, default: str | None = None) -> str | None:
    value = all_values(db).get(key)
    return value if value not in (None, "") else default


def hints(db: Session) -> dict[str, str | None]:
    """Display hints for secret settings — never the secret."""
    return {
        row.key: row.hint
        for row in db.scalars(select(PlatformSetting).where(PlatformSetting.secret.isnot(None)))
    }


def put(
    db: Session,
    key: str,
    value: str | None,
    *,
    secret: bool = False,
    actor_id: str | None = None,
) -> None:
    """Store one setting. An empty value removes it, which is how the portal
    clears an API key and falls back to whatever the environment provides."""
    row = db.scalar(select(PlatformSetting).where(PlatformSetting.key == key))

    if value is None or value == "":
        if row is not None:
            db.delete(row)
        invalidate()
        return

    if row is None:
        row = PlatformSetting(key=key)
        db.add(row)

    if secret:
        row.secret = _seal(value)
        row.value = None
        row.hint = f"…{value[-4:]}" if len(value) > 4 else "…"
    else:
        row.value = value
        row.secret = None
        row.hint = None
    row.updated_by_id = actor_id
    invalidate()
