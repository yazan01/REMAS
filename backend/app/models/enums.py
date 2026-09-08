from __future__ import annotations

from enum import StrEnum


class ServiceLayer(StrEnum):
    """The three commercial layers described in BRD FR-01."""

    QUICK_SCORE = "quick_score"
    AI_REPORT = "ai_report"
    DEEP_DIVE = "deep_dive"


class UserRole(StrEnum):
    IVALUE_ADMIN = "ivalue_admin"
    IVALUE_REVIEWER = "ivalue_reviewer"
    ORG_OWNER = "org_owner"
    ORG_ADMIN = "org_admin"
    CONTRIBUTOR = "contributor"
    VIEWER = "viewer"


IVALUE_ROLES = {UserRole.IVALUE_ADMIN, UserRole.IVALUE_REVIEWER}
ORG_MANAGER_ROLES = {UserRole.ORG_OWNER, UserRole.ORG_ADMIN}


class FrameworkStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class AssessmentStatus(StrEnum):
    DRAFT = "draft"
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"
    UNDER_REVIEW = "under_review"
    COMPLETED = "completed"


class EvidenceStatus(StrEnum):
    """BRD FR-18."""

    MISSING = "missing"
    UPLOADED = "uploaded"
    AI_REVIEWED = "ai_reviewed"
    REQUIRES_CLARIFICATION = "requires_clarification"
    VALIDATED = "validated"
    REJECTED = "rejected"
    NOT_APPLICABLE = "not_applicable"


class ResponseType(StrEnum):
    MATURITY_1_5 = "maturity_1_5"


class Locale(StrEnum):
    AR = "ar"
    EN = "en"
