from __future__ import annotations

from sqlalchemy import ForeignKey, Index, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class AuditLog(UUIDMixin, TimestampMixin, Base):
    """Append-only. Every material action is timestamped and attributable
    (BRD non-functional: auditability)."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_org_created", "organization_id", "created_at"),
        Index("ix_audit_entity", "entity_type", "entity_id"),
    )

    organization_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("organizations.id"))
    actor_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id"))
    actor_email: Mapped[str | None] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(32))
    payload: Mapped[dict | None] = mapped_column(JSON)
    ip_address: Mapped[str | None] = mapped_column(String(64))
