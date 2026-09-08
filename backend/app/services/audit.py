from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog, User


def record(
    db: Session,
    *,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    actor: User | None = None,
    organization_id: str | None = None,
    payload: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> AuditLog:
    entry = AuditLog(
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_id=actor.id if actor else None,
        actor_email=actor.email if actor else None,
        organization_id=organization_id or (actor.organization_id if actor else None),
        payload=payload,
        ip_address=ip_address,
    )
    db.add(entry)
    return entry
