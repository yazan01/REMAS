"""Which capabilities each purchased service layer includes (BRD FR-01, §10).

This is an authorisation rule, and it used to live inside the insights *route*
— so the governance route had to import a controller to ask whether a customer
had bought the expert session. An access-control decision reachable only
through an HTTP module is one nobody can unit-test and everybody duplicates.

The `Feature` enum exists for a specific failure it prevents. The gate compares
a call-site string against keys in `settings.layer_features`; a typo on either
side does not raise, it silently changes who is allowed in. Naming the features
once, and validating the configuration against that list at import time, turns
a silent authorisation drift into a startup error.
"""

from __future__ import annotations

from enum import StrEnum

from fastapi import status

from app.core.config import settings
from app.core.errors import APIError
from app.models import Assessment, User
from app.models.enums import IVALUE_ROLES


class Feature(StrEnum):
    """Everything a layer can include. The values are the configuration keys."""

    SCORING = "scoring"
    DASHBOARD = "dashboard"
    EVIDENCE_AI_REVIEW = "evidence_ai_review"
    AI_ANALYSIS = "ai_analysis"
    INITIATIVES = "initiatives"
    ROADMAP = "roadmap"
    PDF_REPORT = "pdf_report"
    EXPERT_REVIEW = "expert_review"


def _validate_configuration() -> None:
    """Fail loudly at import if the configured layers name a feature that does
    not exist — the alternative is a gate that quietly never opens."""
    known = {str(f) for f in Feature}
    unknown = {
        f"{layer}:{feature}"
        for layer, features in settings.layer_features.items()
        for feature in features
        if feature not in known
    }
    if unknown:
        raise RuntimeError(
            "layer_features names unknown feature(s): " + ", ".join(sorted(unknown))
        )


_validate_configuration()


def allowed(layer: str) -> list[str]:
    return list(settings.layer_features.get(layer, []))


def includes(assessment: Assessment, feature: Feature | str) -> bool:
    return str(feature) in allowed(assessment.layer)


def require(assessment: Assessment, feature: Feature | str, user: User) -> None:
    """Raise 402 unless this assessment's layer includes the capability.

    iValue staff bypass the gate: a reviewer prepares the report before the
    customer's layer is upgraded, and blocking that would make the review
    workflow depend on the billing state.
    """
    if user.role in IVALUE_ROLES:
        return
    if not includes(assessment, feature):
        raise APIError(
            "layer.feature_not_included",
            status.HTTP_402_PAYMENT_REQUIRED,
            {"layer": assessment.layer, "feature": str(feature)},
        )
