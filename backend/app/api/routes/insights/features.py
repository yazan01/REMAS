"""What an assessment's service layer unlocks — BRD FR-01 / section 10.

The read side of `services/entitlements.py`. It sits in its own module because
it is not an AI, initiative or report concern: it is the question all three ask
before offering a control, and the answer the UI needs so it can render the
right tabs instead of guessing and then handling a 403.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_assessment
from app.core.config import settings
from app.models import Assessment
from app.services import entitlements

router = APIRouter(tags=["insights"])


@router.get("/assessments/{assessment_id}/layer-features", response_model=dict)
def layer_features(assessment: Assessment = Depends(get_assessment)) -> dict:
    """What this assessment's service layer unlocks — drives which controls the
    UI offers rather than the UI guessing."""
    return {
        "layer": assessment.layer,
        "features": entitlements.allowed(assessment.layer),
        "all_layers": settings.layer_features,
    }
