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
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "code": "validation.failed",
            "message_ar": message_ar,
            "message_en": message_en,
            "details": {"errors": [{k: str(v) for k, v in e.items()} for e in errors]},
        },
    )
