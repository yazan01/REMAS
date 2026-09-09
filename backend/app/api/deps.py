from __future__ import annotations

from collections.abc import Iterable

from fastapi import Depends, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.errors import APIError
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import Assessment, User
from app.models.enums import IVALUE_ROLES, ORG_MANAGER_ROLES, UserRole

bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise APIError("auth.not_authenticated", status.HTTP_401_UNAUTHORIZED)
    payload = decode_access_token(credentials.credentials)
    if not payload or "sub" not in payload:
        raise APIError("auth.not_authenticated", status.HTTP_401_UNAUTHORIZED)
    user = db.get(User, payload["sub"])
    if user is None or not user.is_active:
        raise APIError("auth.account_disabled", status.HTTP_401_UNAUTHORIZED)
    return user


def require_roles(*roles: UserRole):
    allowed = set(roles)

    def _guard(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise APIError("auth.forbidden", status.HTTP_403_FORBIDDEN)
        return user

    return _guard


def require_ivalue(user: User = Depends(get_current_user)) -> User:
    if user.role not in IVALUE_ROLES:
        raise APIError("auth.forbidden", status.HTTP_403_FORBIDDEN)
    return user


def require_ivalue_admin(user: User = Depends(get_current_user)) -> User:
    """Stricter than `require_ivalue`: a reviewer may read and review, but only
    an administrator may change who can log in or what role they hold."""
    if user.role != UserRole.IVALUE_ADMIN:
        raise APIError("auth.forbidden", status.HTTP_403_FORBIDDEN)
    return user


def can_manage_org(user: User) -> bool:
    return user.role in ORG_MANAGER_ROLES or user.role in IVALUE_ROLES


def get_assessment(
    assessment_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Assessment:
    """Tenant isolation gate: an assessment is only reachable from inside its own
    organisation, or by iValue staff (BRD FR-03)."""
    assessment = db.get(Assessment, assessment_id)
    if assessment is None:
        raise APIError("assessment.not_found", status.HTTP_404_NOT_FOUND)
    if assessment.organization_id != user.organization_id and user.role not in IVALUE_ROLES:
        # Same response as "missing" so the API never confirms existence
        # of another tenant's record.
        raise APIError("assessment.not_found", status.HTTP_404_NOT_FOUND)
    return assessment


def client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def roles_list(roles: Iterable[UserRole]) -> list[str]:
    return [str(r) for r in roles]
