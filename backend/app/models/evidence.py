from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
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
from app.models.enums import EvidenceStatus


class Document(UUIDMixin, TimestampMixin, Base):
    """A file in the organisation's evidence repository. Stored once, linked to
    as many questions as it supports (BRD FR-14 / FR-16)."""

    __tablename__ = "documents"
    __table_args__ = (Index("ix_documents_org", "organization_id"),)

    organization_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(300), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    supersedes_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("documents.id"))
    category: Mapped[str | None] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    uploaded_by_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Populated by the AI pipeline (AI-01): extracted text, page map, metadata.
    extraction: Mapped[dict | None] = mapped_column(JSON)

    links: Mapped[list["DocumentLink"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class DocumentLink(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "document_links"
    __table_args__ = (
        UniqueConstraint("assessment_id", "question_id", "document_id", name="uq_doc_link"),
        Index("ix_doc_links_assessment", "assessment_id"),
    )

    document_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    assessment_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False
    )
    question_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("questions.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(40), default=EvidenceStatus.UPLOADED, nullable=False
    )
    reviewer_note: Mapped[str | None] = mapped_column(Text)
    linked_by_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id"))

    document: Mapped[Document] = relationship(back_populates="links")
