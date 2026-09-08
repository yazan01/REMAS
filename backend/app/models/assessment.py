from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.models.enums import AssessmentStatus, ServiceLayer


class Assessment(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "assessments"

    organization_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    framework_version_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("framework_versions.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    layer: Mapped[str] = mapped_column(String(30), default=ServiceLayer.QUICK_SCORE, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default=AssessmentStatus.DRAFT, nullable=False)

    # Empty list = every axis in the version (BRD FR-07 allows a subset).
    selected_axis_ids: Mapped[list] = mapped_column(JSON, default=list)

    created_by_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_by_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id"))
    locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # FR-12 - an assessment-wide deadline; individual questions may set their own.
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Frozen at submission so historical results stay reproducible (BRD FR-22).
    scoring_snapshot: Mapped[dict | None] = mapped_column(JSON)

    responses: Mapped[list["Response"]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan"
    )

    @property
    def is_open(self) -> bool:
        return not self.locked and self.status in (
            AssessmentStatus.DRAFT,
            AssessmentStatus.IN_PROGRESS,
        )


class Response(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "responses"
    __table_args__ = (
        UniqueConstraint("assessment_id", "question_id", name="uq_response_question"),
        Index("ix_responses_assessment", "assessment_id"),
    )

    assessment_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False
    )
    question_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("questions.id", ondelete="CASCADE"), nullable=False
    )
    score: Mapped[int | None] = mapped_column(Integer)
    is_not_applicable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    na_rationale: Mapped[str | None] = mapped_column(Text)
    comment: Mapped[str | None] = mapped_column(Text)
    answered_by_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id"))
    # Question assignment and deadline (project scope: question assignments;
    # FR-12: overdue items).
    assigned_to_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id"))
    assigned_by_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id"))
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Reviewer override — kept apart from the customer answer so the calculated
    # score stays deterministic and the delta is reportable (BRD FR-23 / FR-24).
    override_score: Mapped[int | None] = mapped_column(Integer)
    override_reason: Mapped[str | None] = mapped_column(Text)
    override_by_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id"))
    override_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    assessment: Mapped[Assessment] = relationship(back_populates="responses")

    @property
    def effective_score(self) -> int | None:
        if self.is_not_applicable:
            return None
        return self.override_score if self.override_score is not None else self.score

    @property
    def is_answered(self) -> bool:
        return self.is_not_applicable or self.effective_score is not None


class ScoringRun(UUIDMixin, TimestampMixin, Base):
    """Every calculation is recorded so a result can always be traced back to the
    inputs, config version and actor that produced it (BRD FR-26)."""

    __tablename__ = "scoring_runs"

    assessment_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False
    )
    triggered_by_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id"))
    reason: Mapped[str | None] = mapped_column(String(200))
    overall_score: Mapped[float | None] = mapped_column(Float)
    maturity_level: Mapped[int | None] = mapped_column(Integer)
    config_used: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
