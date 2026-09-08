from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.api.deps import can_manage_org, client_ip, get_current_user
from app.core.errors import APIError
from app.db.session import get_db
from app.models import Organization, User
from app.schemas import OrganizationOut, OrganizationUpdate
from app.services import audit

router = APIRouter(prefix="/organization", tags=["organization"])

# The onboarding checklist of BRD FR-04. Held server-side so the steps stay in
# one place for the dashboard, the reminder emails and the reviewer view.
ONBOARDING_STEPS = [
    {"key": "organization_profile", "label_ar": "استكمال ملف المنشأة", "label_en": "Complete the organisation profile"},
    {"key": "invite_users", "label_ar": "دعوة أعضاء الفريق", "label_en": "Invite team members"},
    {"key": "create_assessment", "label_ar": "إنشاء تقييم", "label_en": "Create an assessment"},
    {"key": "answer_questions", "label_ar": "إكمال الاستبيان", "label_en": "Complete the questionnaire"},
    {"key": "upload_evidence", "label_ar": "رفع المستندات الداعمة", "label_en": "Upload supporting evidence"},
    {"key": "submit", "label_ar": "تقديم التقييم", "label_en": "Submit the assessment"},
    {"key": "review", "label_ar": "مراجعة iValue", "label_en": "iValue review"},
    {"key": "final_report", "label_ar": "إصدار التقرير النهائي", "label_en": "Final report release"},
]


@router.get("", response_model=OrganizationOut)
def get_organization(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Organization:
    org = db.get(Organization, user.organization_id)
    if org is None:
        raise APIError("org.not_found", status.HTTP_404_NOT_FOUND)
    return org


@router.patch("", response_model=OrganizationOut)
def update_organization(
    payload: OrganizationUpdate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Organization:
    if not can_manage_org(user):
        raise APIError("auth.forbidden", status.HTTP_403_FORBIDDEN)
    org = db.get(Organization, user.organization_id)
    if org is None:
        raise APIError("org.not_found", status.HTTP_404_NOT_FOUND)

    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    for key, value in changes.items():
        setattr(org, key, value)

    audit.record(
        db,
        action="organization.updated",
        entity_type="organization",
        entity_id=org.id,
        actor=user,
        payload={"fields": sorted(changes)},
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(org)
    return org


@router.get("/onboarding", response_model=list[dict])
def onboarding() -> list[dict]:
    return ONBOARDING_STEPS
