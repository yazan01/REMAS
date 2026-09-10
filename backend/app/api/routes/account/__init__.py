"""Account security and team management — the FR-03 / FR-04 surface.

Split from one 402-line module along the boundaries it already documented:

    passwords   reset request, reset confirm, change (FR-03)
    mfa         TOTP enrolment, confirmation, removal (FR-03 + security NFR)
    team        invitations and the member register (FR-04)

The `/account` prefix lives here, so each module below spells only the part of
the path that is its own.
"""

from fastapi import APIRouter

from app.api.routes.account import mfa, passwords, team

router = APIRouter(prefix="/account", tags=["account"])

for _part in (passwords, mfa, team):
    router.include_router(_part.router)

__all__ = ["router"]
