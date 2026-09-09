"""Bilingual API errors.

Every error carries both languages so the client can switch locale without
re-issuing the request — the same rule the content engine follows.
"""

from __future__ import annotations

from fastapi import Request, status
from fastapi.responses import JSONResponse

MESSAGES: dict[str, tuple[str, str]] = {
    "auth.email_taken": ("هذا البريد الإلكتروني مسجّل مسبقاً.", "That email is already registered."),
    "auth.invalid_credentials": (
        "البريد الإلكتروني أو كلمة المرور غير صحيحة.",
        "Incorrect email or password.",
    ),
    "auth.email_not_verified": (
        "يجب تأكيد البريد الإلكتروني قبل تسجيل الدخول.",
        "Verify your email address before signing in.",
    ),
    "auth.invalid_token": ("رابط التحقق غير صالح أو منتهي.", "This verification link is invalid or expired."),
    "auth.account_disabled": ("الحساب معطّل. تواصل مع مسؤول المنشأة.", "This account is disabled. Contact your organisation admin."),
    "auth.not_authenticated": ("يلزم تسجيل الدخول.", "Sign in to continue."),
    "auth.forbidden": ("لا تملك صلاحية لهذا الإجراء.", "You do not have permission for this action."),
    "org.not_found": ("المنشأة غير موجودة.", "Organisation not found."),
    "framework.not_found": ("إطار التقييم غير موجود.", "Assessment framework not found."),
    "framework.no_published_version": (
        "لا توجد نسخة منشورة من إطار التقييم.",
        "No published framework version is available.",
    ),
    "assessment.not_found": ("التقييم غير موجود.", "Assessment not found."),
    "assessment.locked": (
        "التقييم مقفل ولا يمكن تعديله.",
        "This assessment is locked and can no longer be edited.",
    ),
    "assessment.already_submitted": ("تم تقديم هذا التقييم مسبقاً.", "This assessment has already been submitted."),
    "assessment.mandatory_incomplete": (
        "لا يمكن التقديم قبل الإجابة على كل الأسئلة الإلزامية.",
        "All mandatory questions must be answered before submitting.",
    ),
    "assessment.not_submitted": (
        "النتائج تُحتسب بعد تقديم التقييم.",
        "Results become available after the assessment is submitted.",
    ),
    "question.not_in_assessment": (
        "هذا السؤال لا ينتمي إلى محاور التقييم المختارة.",
        "This question is not part of the selected assessment axes.",
    ),
    "question.na_not_allowed": (
        "خيار «غير منطبق» غير متاح لهذا السؤال.",
        "\"Not applicable\" is not permitted for this question.",
    ),
    "response.score_required": ("يجب اختيار درجة أو تحديد «غير منطبق».", "Choose a score or mark the question not applicable."),
    "document.not_found": ("المستند غير موجود.", "Document not found."),
    "document.too_large": ("حجم الملف يتجاوز الحد المسموح.", "The file exceeds the maximum allowed size."),
    "document.unsupported_type": (
        "نوع الملف غير مدعوم. المسموح: PDF، DOCX، XLSX، PPTX، PNG، JPG.",
        "Unsupported file type. Allowed: PDF, DOCX, XLSX, PPTX, PNG, JPG.",
    ),
    "auth.reset_expired": ("انتهت صلاحية رابط استعادة كلمة المرور.", "This password reset link has expired."),
    "auth.invite_expired": ("انتهت صلاحية الدعوة.", "This invitation has expired."),
    "auth.mfa_not_enrolled": ("لم يتم تفعيل التحقق بخطوتين بعد.", "Two-factor authentication is not set up yet."),
    "auth.mfa_invalid": ("رمز التحقق غير صحيح.", "That verification code is not correct."),
    "auth.mfa_required": ("مطلوب رمز التحقق بخطوتين.", "A two-factor code is required."),
    "auth.mfa_required_for_role": (
        "لا يمكن تعطيل التحقق بخطوتين لحسابات المسؤولين.",
        "Two-factor authentication cannot be disabled for administrator accounts.",
    ),
    "framework.version_locked": (
        "لا يمكن تعديل نسخة منشورة. أنشئ نسخة جديدة منها ثم عدّلها.",
        "A published version cannot be edited. Clone it into a new draft first.",
    ),
    "framework.code_taken": ("رمز الإطار مستخدم مسبقاً.", "That framework code is already in use."),
    "framework.version_taken": ("رقم النسخة مستخدم مسبقاً.", "That version number is already in use."),
    "framework.empty_version": ("لا يمكن نشر نسخة بلا محاور.", "A version with no pillars cannot be published."),
    "scoring.unknown_formula": ("معادلة احتساب غير معروفة.", "Unknown scoring formula."),
    "scoring.unknown_na_handling": ("طريقة معالجة «غير منطبق» غير معروفة.", "Unknown not-applicable handling."),
    "import.empty_file": ("الملف فارغ أو لا يحتوي على صفوف صالحة.", "The file is empty or has no usable rows."),
    "import.unsupported_format": (
        "صيغة غير مدعومة. استخدم XLSX أو CSV.",
        "Unsupported format. Use XLSX or CSV.",
    ),
    "ai.disabled": ("خدمة التحليل الآلي معطّلة.", "Automated analysis is disabled."),
    "ai.finding_not_found": ("الملاحظة غير موجودة.", "Finding not found."),
    "layer.feature_not_included": (
        "هذه الميزة غير متضمّنة في طبقة الخدمة المختارة.",
        "This feature is not included in the selected service layer.",
    ),
    "roadmap.initiative_not_found": ("المبادرة غير موجودة.", "Initiative not found."),
    "report.render_failed": ("تعذّر توليد التقرير.", "The report could not be generated."),
    "assessment.override_not_permitted": (
        "التقديم رغم النقص يتطلب صلاحية iValue.",
        "Submitting with gaps requires iValue authorisation.",
    ),
    "report.template_not_found": ("قالب التقرير غير موجود.", "Report template not found."),
    "report.template_code_taken": ("رمز القالب مستخدم مسبقاً.", "That template code is already in use."),
    "report.unknown_section": (
        "قسم غير معروف في قالب التقرير.",
        "Unknown section in the report template.",
    ),
    "expert_session.not_found": ("جلسة الخبير غير موجودة.", "Expert session not found."),
    "document.not_previewable": (
        "لا يمكن معاينة هذا النوع من الملفات — استخدم التحميل.",
        "This file type cannot be previewed; download it instead.",
    ),
    "auth.user_not_found": ("المستخدم غير موجود.", "User not found."),
    "auth.unknown_role": ("دور غير معروف.", "Unknown role."),
    "auth.cannot_demote_self": (
        "لا يمكنك تعطيل حسابك أو خفض صلاحيتك بنفسك.",
        "You cannot disable or demote your own account.",
    ),
    "auth.last_admin": (
        "لا يمكن خفض صلاحية آخر مسؤول في المنصة.",
        "The last platform administrator cannot be demoted.",
    ),
    "validation.failed": ("البيانات المُرسلة غير صالحة.", "The submitted data is not valid."),
    "server.error": ("حدث خطأ غير متوقع.", "Something went wrong."),
}


class APIError(Exception):
    def __init__(
        self,
        code: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: dict | None = None,
    ) -> None:
        self.code = code
        self.status_code = status_code
        self.details = details or {}
        super().__init__(code)

    def payload(self) -> dict:
        message_ar, message_en = MESSAGES.get(self.code, MESSAGES["server.error"])
        return {
            "code": self.code,
            "message_ar": message_ar,
            "message_en": message_en,
            "details": self.details,
        }


async def api_error_handler(_request: Request, exc: APIError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=exc.payload())


async def validation_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    errors = getattr(exc, "errors", lambda: [])()
    hint = None
    for err in errors:
        raw = str(err.get("msg", ""))
        for code in ("na_rationale_required",):
            if code in raw:
                hint = code
    message_ar, message_en = MESSAGES["validation.failed"]
    if hint == "na_rationale_required":
        message_ar = "يلزم كتابة مبرر عند اختيار «غير منطبق»."
        message_en = "A rationale is required when marking a question not applicable."
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "code": "validation.failed",
            "message_ar": message_ar,
            "message_en": message_en,
            "details": {"errors": [{k: str(v) for k, v in e.items()} for e in errors]},
        },
    )
