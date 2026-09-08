"""Report templates, expert sessions and work assignment.

Closes the BRD items the first build left open: FR-34 (configurable report
templates), FR-12 (overdue items and completion by user), question assignment
from the project scope, and the Layer 3 expert meeting from section 10.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin

# The seven sections the BRD's section 9 requires. A template may reorder them,
# retitle them or switch one off, but the keys are fixed so the renderer always
# knows what it is drawing.
REPORT_SECTIONS = [
    "cover",
    "executive_summary",
    "maturity_results",
    "axis_findings",
    "priorities",
    "initiatives",
    "roadmap",
]

DEFAULT_SECTIONS = [
    {"key": key, "enabled": True, "order": index, "title_ar": None, "title_en": None}
    for index, key in enumerate(REPORT_SECTIONS)
]

DEFAULT_BRANDING = {
    "primary": "#1e3a5c",
    "accent": "#b8863b",
    "ink": "#0f1b28",
    "muted": "#6b7d8d",
    "line": "#dbe2e9",
    "surface_alt": "#f6f8fa",
    "ramp": ["#c9d2db", "#9db4cc", "#6d8fb2", "#426b95", "#1e3a5c"],
    "logo_data_uri": None,
    "organisation_name": "iValue Consult",
    "footer_ar": "أُعد بواسطة iValue Consult",
    "footer_en": "Prepared by iValue Consult",
    "confidentiality_ar": "وثيقة سرّية — للاستخدام الداخلي لدى العميل و iValue Consult فقط.",
    "confidentiality_en": "Confidential — for the client and iValue Consult only.",
}


class ReportTemplate(UUIDMixin, TimestampMixin, Base):
    """FR-34 — administrators customise report sections, recommendations text,
    the maturity scale wording, branding and output formats without a code
    change. The renderer reads this; nothing about a report is hard-coded."""

    __tablename__ = "report_templates"
    __table_args__ = (UniqueConstraint("framework_version_id", "code", name="uq_report_template"),)

    framework_version_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("framework_versions.id", ondelete="CASCADE")
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name_ar: Mapped[str] = mapped_column(String(200), nullable=False)
    name_en: Mapped[str] = mapped_column(String(200), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    sections: Mapped[list] = mapped_column(JSON, default=lambda: list(DEFAULT_SECTIONS))
    branding: Mapped[dict] = mapped_column(JSON, default=lambda: dict(DEFAULT_BRANDING))
    # Free-text blocks an administrator can inject, keyed by section.
    copy_blocks: Mapped[dict] = mapped_column(JSON, default=dict)
    # pdf | html | json — which downloads this template offers.
    output_formats: Mapped[list] = mapped_column(JSON, default=lambda: ["pdf", "html", "json"])
    # Maturity scale wording override, keyed by score. Falls back to the
    # framework version's own levels when absent.
    maturity_labels: Mapped[dict] = mapped_column(JSON, default=dict)
    include_comparison: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class ExpertSession(UUIDMixin, TimestampMixin, Base):
    """The Layer 3 online meeting with an expert (BRD section 10)."""

    __tablename__ = "expert_sessions"

    assessment_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False
    )
    requested_by_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id"))
    expert_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id"))

    status: Mapped[str] = mapped_column(String(20), default="requested", nullable=False)
    # requested | scheduled | completed | cancelled
    preferred_slots: Mapped[list] = mapped_column(JSON, default=list)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_minutes: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    meeting_url: Mapped[str | None] = mapped_column(String(500))
    agenda: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
