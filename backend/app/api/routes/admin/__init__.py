"""Administration portal API — BRD FR-31 → FR-35.

Everything an administrator needs to configure the platform *without a code
change*. One router per responsibility, mounted under a single `/admin` prefix
so every URL is exactly what it was when this was one 1352-line module:

    frameworks   frameworks, versions, publishing, scoring configuration
    content      axes, questions, maturity levels
    library      delivery horizons and the initiative catalogue
    importing    bulk load from iValue's master sheet
    tenants      customer organisations and the audit trail
    users        the user register across every tenant
    ai_settings  AI provider selection and its API key
    report_templates  report sections, branding and output formats (FR-34)

The version rule enforced throughout: a published version is immutable. Editing
means cloning to a new draft, changing that, and publishing it — which is what
keeps historical assessments reproducible (FR-35).
"""

from fastapi import APIRouter

from app.api.routes.admin import (
    ai_settings,
    content,
    frameworks,
    importing,
    library,
    report_templates,
    tenants,
    users,
)

router = APIRouter(prefix="/admin", tags=["admin"])

for _part in (
    frameworks,
    content,
    library,
    importing,
    tenants,
    users,
    ai_settings,
    report_templates,
):
    router.include_router(_part.router)

__all__ = ["router"]
