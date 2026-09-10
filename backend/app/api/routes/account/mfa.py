"""TOTP multi-factor authentication — BRD FR-03 and the security NFR.

Mandatory for administrator roles, which is why enrolment cannot simply be
switched back off once an administrator has it: the delete route refuses for
those roles rather than quietly lowering the bar on the most privileged
accounts.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import client_ip, get_current_user
from app.core.errors import APIError
from app.db.session import get_db
from app.models import User
from app.models.enums import IVALUE_ROLES
from app.services import audit

router = APIRouter()
log = logging.getLogger("remas.account")

#: Shown in the authenticator app beside the account name.
MFA_ISSUER = "REMAS"



class MfaEnrolOut(BaseModel):
    secret: str
    otpauth_uri: str
    already_enabled: bool


class MfaVerifyIn(BaseModel):
    code: str = Field(min_length=6, max_length=8)


@router.post("/mfa/enrol", response_model=MfaEnrolOut)
def enrol_mfa(
    request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> MfaEnrolOut:
    """Issues a TOTP secret. It is not active until a valid code confirms the
    authenticator app is in sync."""
    import pyotp

    if not user.mfa_secret or not user.mfa_enabled:
        user.mfa_secret = pyotp.random_base32()
        db.commit()

    uri = pyotp.TOTP(user.mfa_secret).provisioning_uri(name=user.email, issuer_name=MFA_ISSUER)
    audit.record(
        db,
        action="user.mfa_enrolment_started",
        entity_type="user",
        entity_id=user.id,
        actor=user,
        ip_address=client_ip(request),
    )
    db.commit()
    return MfaEnrolOut(
        secret=user.mfa_secret, otpauth_uri=uri, already_enabled=user.mfa_enabled
    )


@router.post("/mfa/confirm", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def confirm_mfa(
    payload: MfaVerifyIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    import pyotp

    if not user.mfa_secret:
        raise APIError("auth.mfa_not_enrolled", status.HTTP_400_BAD_REQUEST)
    if not pyotp.TOTP(user.mfa_secret).verify(payload.code, valid_window=1):
        raise APIError("auth.mfa_invalid", status.HTTP_401_UNAUTHORIZED)

    user.mfa_enabled = True
    audit.record(
        db,
        action="user.mfa_enabled",
        entity_type="user",
        entity_id=user.id,
        actor=user,
        ip_address=client_ip(request),
    )
    db.commit()


@router.delete("/mfa", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def disable_mfa(
    payload: MfaVerifyIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    import pyotp

    # The security NFR makes MFA mandatory for administrator roles, so an admin
    # cannot turn it back off.
    if user.role in IVALUE_ROLES:
        raise APIError("auth.mfa_required_for_role", status.HTTP_403_FORBIDDEN)
    if not user.mfa_secret or not pyotp.TOTP(user.mfa_secret).verify(payload.code, valid_window=1):
        raise APIError("auth.mfa_invalid", status.HTTP_401_UNAUTHORIZED)

    user.mfa_enabled = False
    user.mfa_secret = None
    audit.record(
        db,
        action="user.mfa_disabled",
        entity_type="user",
        entity_id=user.id,
        actor=user,
        ip_address=client_ip(request),
    )
    db.commit()


