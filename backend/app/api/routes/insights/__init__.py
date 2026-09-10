"""Everything that happens to an assessment after it is submitted.

This was one 546-line module holding three unrelated conversations. They are
split along the seams the file itself had already drawn in comment banners:

    ai            the five-stage pipeline and the human review gate (AI-01→07)
    initiatives   improvement initiatives and the roadmap (FR-28→30)
    reports       HTML, PDF, structured export, release gate (section 9)
    features      which controls this assessment's layer unlocks (FR-01)

No prefix is applied here. These routes hang off several different roots
(`/assessments/...`, `/ai/findings/...`, `/initiatives/...`), so each module
spells its own full path exactly as it did before the split.
"""

from fastapi import APIRouter

from app.api.routes.insights import ai, features, initiatives, reports

router = APIRouter()

for _part in (ai, initiatives, reports, features):
    router.include_router(_part.router)

__all__ = ["router"]
