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
from app.models.enums import FrameworkStatus, ResponseType

DEFAULT_SCORING_CONFIG: dict = {
    # Weighted average. The BRD (p.7) divides by question count, which pushes
    # results outside the 1-5 scale whenever weights differ from 1; dividing by
    # the sum of weights is the mathematically correct form and is what ships
    # until iValue signs off on the final formula.
    "formula": "weighted_average",
    "na_handling": "exclude",  # exclude | zero
    "min_axis_coverage": 0.6,
    "scale_min": 1,
    "scale_max": 5,
    "thresholds": [
        {"level": 5, "min_score": 4.5},
        {"level": 4, "min_score": 3.5},
        {"level": 3, "min_score": 2.5},
        {"level": 2, "min_score": 1.5},
        {"level": 1, "min_score": 0.0},
    ],
}


class Framework(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "frameworks"

    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name_ar: Mapped[str] = mapped_column(String(200), nullable=False)
    name_en: Mapped[str] = mapped_column(String(200), nullable=False)
    description_ar: Mapped[str | None] = mapped_column(Text)
    description_en: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    versions: Mapped[list["FrameworkVersion"]] = relationship(
        back_populates="framework", cascade="all, delete-orphan"
    )


class FrameworkVersion(UUIDMixin, TimestampMixin, Base):
    """A published version is immutable: editing content creates a new version so
    historical assessments stay reproducible (BRD FR-22, FR-35)."""

    __tablename__ = "framework_versions"
    __table_args__ = (UniqueConstraint("framework_id", "version", name="uq_framework_version"),)

    framework_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("frameworks.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=FrameworkStatus.DRAFT, nullable=False)
    scoring_config: Mapped[dict] = mapped_column(JSON, default=lambda: dict(DEFAULT_SCORING_CONFIG))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_note: Mapped[str | None] = mapped_column(Text)

    framework: Mapped[Framework] = relationship(back_populates="versions")
    axes: Mapped[list["Axis"]] = relationship(
        back_populates="framework_version",
        cascade="all, delete-orphan",
        order_by="Axis.order_index",
    )
    maturity_levels: Mapped[list["MaturityLevel"]] = relationship(
        back_populates="framework_version",
        cascade="all, delete-orphan",
        order_by="MaturityLevel.score",
    )

    @property
    def is_editable(self) -> bool:
        return self.status == FrameworkStatus.DRAFT


class MaturityLevel(UUIDMixin, Base):
    """The 1-5 scale, stored as data so labels are configurable (BRD FR-33)."""

    __tablename__ = "maturity_levels"
    __table_args__ = (UniqueConstraint("framework_version_id", "score", name="uq_level_score"),)

    framework_version_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("framework_versions.id", ondelete="CASCADE"), nullable=False
    )
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    label_ar: Mapped[str] = mapped_column(String(80), nullable=False)
    label_en: Mapped[str] = mapped_column(String(80), nullable=False)
    description_ar: Mapped[str | None] = mapped_column(Text)
    description_en: Mapped[str | None] = mapped_column(Text)

    framework_version: Mapped[FrameworkVersion] = relationship(back_populates="maturity_levels")


class Axis(UUIDMixin, Base):
    """One of the 16 assessment pillars."""

    __tablename__ = "axes"
    __table_args__ = (UniqueConstraint("framework_version_id", "code", name="uq_axis_code"),)

    framework_version_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("framework_versions.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    name_ar: Mapped[str] = mapped_column(String(200), nullable=False)
    name_en: Mapped[str] = mapped_column(String(200), nullable=False)
    description_ar: Mapped[str | None] = mapped_column(Text)
    description_en: Mapped[str | None] = mapped_column(Text)
    weight: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)

    framework_version: Mapped[FrameworkVersion] = relationship(back_populates="axes")
    questions: Mapped[list["Question"]] = relationship(
        back_populates="axis", cascade="all, delete-orphan", order_by="Question.order_index"
    )


class Question(UUIDMixin, Base):
    __tablename__ = "questions"
    __table_args__ = (UniqueConstraint("axis_id", "code", name="uq_question_code"),)

    axis_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("axes.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    text_ar: Mapped[str] = mapped_column(Text, nullable=False)
    text_en: Mapped[str] = mapped_column(Text, nullable=False)
    guidance_ar: Mapped[str | None] = mapped_column(Text)
    guidance_en: Mapped[str | None] = mapped_column(Text)
    evidence_hint_ar: Mapped[str | None] = mapped_column(Text)
    evidence_hint_en: Mapped[str | None] = mapped_column(Text)

    weight: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    is_mandatory: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    evidence_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    allow_not_applicable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    response_type: Mapped[str] = mapped_column(
        String(30), default=ResponseType.MATURITY_1_5, nullable=False
    )
    # Per-level wording ("what does a 3 look like for this question")
    criteria: Mapped[dict | None] = mapped_column(JSON)

    axis: Mapped[Axis] = relationship(back_populates="questions")
