"""Running an assessment as a piece of work, rather than as a form.

    assignments       who owns which question, by when, and what is late (FR-12)
    expert_sessions   the Layer 3 expert meeting (section 10)

No prefix: these routes hang off `/assessments/...` and `/expert-sessions/...`,
so each module spells its own full path.

Report templates lived here too until they moved to
`admin/report_templates.py`, where the rest of the platform configuration is.
"""

from fastapi import APIRouter

from app.api.routes.governance import assignments, expert_sessions

router = APIRouter()

for _part in (assignments, expert_sessions):
    router.include_router(_part.router)

__all__ = ["router"]
