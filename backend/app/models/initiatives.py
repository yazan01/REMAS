from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin


class RoadmapHorizon(UUIDMixin, TimestampMixin, Base):
    """Delivery horizons — labels and periods configurable by iValue (FR-29)."""

    __tablename__ = "roadmap_horizons"
    __table_args__ = (UniqueConstraint("framework_version_id", "code", name="uq_horizon_code"),)

    framework_version_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("framework_versions.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    name_ar: Mapped[str] = mapped_column(String(120), nullable=False)
    name_en: Mapped[str] = mapped_column(String(120), nullable=False)
    months_from: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    months_to: Mapped[int] = mapped_column(Integer, default=3, nullable=False)


class InitiativeTemplate(UUIDMixin, TimestampMixin, Base):
    """iValue's reusable initiative library, keyed to an axis and a maturity band.
    The recommendation engine draws from here so every suggestion is traceable to
    approved content rather than invented at generation time (FR-28)."""

    __tablename__ = "initiative_templates"

    framework_version_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("framework_versions.id", ondelete="CASCADE"), nullable=False
    )
    axis_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("axes.id", ondelete="CASCADE")
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    title_ar: Mapped[str] = mapped_column(String(300), nullable=False)
    title_en: Mapped[str] = mapped_column(String(300), nullable=False)
    objective_ar: Mapped[str | None] = mapped_column(Text)
    objective_en: Mapped[str | None] = mapped_column(Text)
    rationale_ar: Mapped[str | None] = mapped_column(Text)
    rationale_en: Mapped[str | None] = mapped_column(Text)
    owner_function_ar: Mapped[str | None] = mapped_column(String(160))
    owner_function_en: Mapped[str | None] = mapped_column(String(160))
    dependencies_ar: Mapped[str | None] = mapped_column(Text)
    dependencies_en: Mapped[str | None] = mapped_column(Text)

    # Applies when the axis score sits inside this band.
    applies_min_score: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    applies_max_score: Mapped[float] = mapped_column(Float, default=5.0, nullable=False)
    default_horizon_code: Mapped[str | None] = mapped_column(String(40))
    effort: Mapped[str | None] = mapped_column(String(30))  # low | medium | high
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Initiative(UUIDMixin, TimestampMixin, Base):
    """An initiative attached to one assessment's results (FR-28, FR-30)."""

    __tablename__ = "initiatives"

    assessment_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False
    )
    axis_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("axes.id"))
    template_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("initiative_templates.id")
    )

    title_ar: Mapped[str] = mapped_column(String(300), nullable=False)
    title_en: Mapped[str] = mapped_column(String(300), nullable=False)
    objective_ar: Mapped[str | None] = mapped_column(Text)
    objective_en: Mapped[str | None] = mapped_column(Text)
    rationale_ar: Mapped[str | None] = mapped_column(Text)
    rationale_en: Mapped[str | None] = mapped_column(Text)
    owner_function_ar: Mapped[str | None] = mapped_column(String(160))
    owner_function_en: Mapped[str | None] = mapped_column(String(160))
    dependencies_ar: Mapped[str | None] = mapped_column(Text)
    dependencies_en: Mapped[str | None] = mapped_column(Text)

    linked_gap: Mapped[str | None] = mapped_column(Text)
    horizon_code: Mapped[str | None] = mapped_column(String(40))
    priority: Mapped[int] = mapped_column(Integer, default=3, nullable=False)  # 1 = highest
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    source: Mapped[str] = mapped_column(String(20), default="engine", nullable=False)
    # engine | ai | reviewer
    is_included: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    edited_by_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id"))
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AIJob(UUIDMixin, TimestampMixin, Base):
    """One run of the AI pipeline over an assessment. Records the provider and
    model so every generated output stays attributable (BRD auditability)."""

    __tablename__ = "ai_jobs"

    assessment_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False
    )
    stage: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    provider: Mapped[str | None] = mapped_column(String(60))
    model: Mapped[str | None] = mapped_column(String(120))
    prompt_version: Mapped[str | None] = mapped_column(String(20))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    triggered_by_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id"))
    summary: Mapped[dict | None] = mapped_column(JSON)

    findings: Mapped[list["AIFinding"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class AIFinding(UUIDMixin, TimestampMixin, Base):
    """A single AI output — evidence check, gap, strength or narrative — always
    carrying its citation so a reviewer can trace it (AI-02, AI-03)."""

    __tablename__ = "ai_findings"

    job_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("ai_jobs.id", ondelete="CASCADE"), nullable=False
    )
    assessment_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False
    )
    axis_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("axes.id"))
    question_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("questions.id"))
    document_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("documents.id"))

    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    # evidence_coverage | strength | gap | opportunity | narrative | recommendation
    severity: Mapped[str | None] = mapped_column(String(20))  # info | low | medium | high
    title_ar: Mapped[str | None] = mapped_column(Text)
    title_en: Mapped[str | None] = mapped_column(Text)
    body_ar: Mapped[str | None] = mapped_column(Text)
    body_en: Mapped[str | None] = mapped_column(Text)

    # Traceability (AI-03): which document, which page, which excerpt.
    citation: Mapped[dict | None] = mapped_column(JSON)
    confidence: Mapped[float | None] = mapped_column(Float)

    review_status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    # draft | accepted | rejected | edited
    reviewed_by_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewer_note: Mapped[str | None] = mapped_column(Text)

    job: Mapped[AIJob] = relationship(back_populates="findings")


class ReportRender(UUIDMixin, TimestampMixin, Base):
    """A generated report artefact, pinned to the scoring run it was built from."""

    __tablename__ = "report_renders"

    assessment_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False
    )
    scoring_run_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("scoring_runs.id"))
    locale: Mapped[str] = mapped_column(String(5), default="ar", nullable=False)
    fmt: Mapped[str] = mapped_column(String(10), default="pdf", nullable=False)
    layer: Mapped[str | None] = mapped_column(String(30))
    stored_path: Mapped[str | None] = mapped_column(String(500))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    released: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    generated_by_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id"))


class Invitation(UUIDMixin, TimestampMixin, Base):
    """Team invitations for the customer workspace (BRD FR-04)."""

    __tablename__ = "invitations"

    organization_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    token: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invited_by_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id"))
