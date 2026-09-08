from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.models.enums import Locale, UserRole


class Organization(UUIDMixin, TimestampMixin, Base):
    """A customer developer organisation — the tenant boundary (BRD FR-02)."""

    __tablename__ = "organizations"

    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name_ar: Mapped[str] = mapped_column(String(200), nullable=False)
    name_en: Mapped[str] = mapped_column(String(200), nullable=False)

    # Developer profile (BRD FR-02 — field list pending iValue confirmation)
    commercial_registration: Mapped[str | None] = mapped_column(String(60))
    city: Mapped[str | None] = mapped_column(String(120))
    country: Mapped[str | None] = mapped_column(String(120))
    website: Mapped[str | None] = mapped_column(String(200))
    employee_count: Mapped[int | None] = mapped_column()
    years_active: Mapped[int | None] = mapped_column()
    annual_projects: Mapped[int | None] = mapped_column()
    primary_segment: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)

    is_ivalue: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    users: Mapped[list["User"]] = relationship(back_populates="organization")

    @property
    def profile_completeness(self) -> float:
        fields = [
            self.commercial_registration,
            self.city,
            self.country,
            self.employee_count,
            self.years_active,
            self.primary_segment,
        ]
        filled = sum(1 for f in fields if f not in (None, ""))
        return round(filled / len(fields), 4)


class User(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "users"

    organization_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(40), default=UserRole.ORG_OWNER, nullable=False)
    locale: Mapped[str] = mapped_column(String(5), default=Locale.AR, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verification_token: Mapped[str | None] = mapped_column(String(80), index=True)
    verification_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reset_token: Mapped[str | None] = mapped_column(String(80), index=True)
    reset_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # MFA (BRD FR-03) — enrolment stored here, enforced at login when enabled.
    mfa_secret: Mapped[str | None] = mapped_column(String(64))
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    organization: Mapped[Organization] = relationship(back_populates="users")

    @property
    def is_ivalue_staff(self) -> bool:
        return self.role in (UserRole.IVALUE_ADMIN, UserRole.IVALUE_REVIEWER)


Index("ix_users_org", User.organization_id)
