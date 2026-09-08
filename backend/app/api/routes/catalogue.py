"""Service catalogue — the layer selection screen (BRD FR-01, section 10).

Held as data rather than markup so the landing page, the pricing card and the
assessment creation form all read one source, in both languages.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.enums import ServiceLayer
from app.schemas import LayerOut

router = APIRouter(prefix="/catalogue", tags=["catalogue"])

LAYERS: list[LayerOut] = [
    LayerOut(
        key=ServiceLayer.QUICK_SCORE,
        name_ar="نتيجة التقييم السريع",
        name_en="Quick Assessment Score",
        summary_ar="لقطة فورية لمستوى النضج المؤسسي الحالي للمطوّر.",
        summary_en="A snapshot of the developer's current institutional maturity level.",
        includes_ar=[
            "وصول مباشر إلى استبيان تقييم النضج",
            "إكمال أسئلة التقييم عبر المحاور الستة عشر",
            "رفع المستندات الداعمة للأسئلة ذات الصلة",
            "مراجعة آلية للإجابات والمستندات المرفقة",
            "احتساب آلي وفق نموذج التقييم المعتمد",
            "ملخّص بصري للنتائج في لوحة المنصة",
        ],
        includes_en=[
            "Online access to the maturity assessment questionnaire",
            "Completion of the assessment questions across the 16 pillars",
            "Upload of supporting documents for the relevant questions",
            "Automated review of submitted answers and attachments",
            "Automated scoring against the approved maturity model",
            "Visual summary of results on the platform dashboard",
        ],
        output_ar="نتيجة نضج سريعة",
        output_en="Quick maturity score",
    ),
    LayerOut(
        key=ServiceLayer.AI_REPORT,
        name_ar="تقرير تقييم عالي المستوى بالذكاء الاصطناعي",
        name_en="AI-Generated High-Level Report",
        summary_ar="تقرير نتيجة مدعوم بتحليل يبرز أبرز مجالات التحسين عبر المحاور الستة عشر.",
        summary_en="A score report with AI analysis highlighting key improvement areas across the 16 pillars.",
        includes_ar=[
            "كل ما تتضمنه الطبقة الأولى",
            "تحليل عالي المستوى عبر المحاور الستة عشر",
            "تحديد نقاط القوة وفجوات النضج",
            "توصيات عالية المستوى مبنية على النتائج",
            "مبادرات تحسين مرتبطة بالفجوات المُحدَّدة",
            "خارطة طريق تنفيذية مُرتَّبة بالأولوية",
            "تقرير تنفيذي قابل للتحميل بصيغة PDF",
        ],
        includes_en=[
            "Everything in Layer 1",
            "High-level analysis across the 16 assessment pillars",
            "Identification of key strengths and maturity gaps",
            "High-level recommendations based on the results",
            "Improvement initiatives linked to the identified gaps",
            "Prioritised implementation roadmap",
            "Downloadable executive report in PDF",
        ],
        output_ar="تقرير نضج عالي المستوى",
        output_en="AI-generated high-level maturity report",
    ),
    LayerOut(
        key=ServiceLayer.DEEP_DIVE,
        name_ar="تقرير التقييم المعمّق",
        name_en="Deep-Dive Maturity Report",
        summary_ar="تقرير مخصّص بمراجعة خبير واجتماع لمناقشة النتائج وتخصيص التوصيات.",
        summary_en="A tailored report validated by an expert, with an online session to review findings.",
        includes_ar=[
            "كل ما تتضمنه الطبقتان الأولى والثانية",
            "مراجعة تفصيلية للإجابات والمستندات المرفوعة",
            "تحقق الخبير من مخرجات الذكاء الاصطناعي",
            "تحليل فجوات مخصّص لكل محور من المحاور الستة عشر",
            "توصيات مخصّصة وفق نموذج عمل المطوّر وسياقه التشغيلي",
            "اجتماع أونلاين مع خبير لمناقشة النتائج وتخصيص التقرير",
        ],
        includes_en=[
            "Everything in Layers 1 and 2",
            "Detailed review of submitted answers and uploaded documents",
            "Expert validation of the AI-generated outputs",
            "Customised gap analysis for each of the 16 pillars",
            "Tailored recommendations for the developer's model and context",
            "Online session with an expert to review and customise the report",
        ],
        output_ar="تقرير معمّق مُراجَع من خبير مع توصيات وخارطة طريق مخصّصة",
        output_en="Expert-reviewed deep-dive report with tailored recommendations and roadmap",
    ),
]


@router.get("/layers", response_model=list[LayerOut])
def list_layers() -> list[LayerOut]:
    return LAYERS


@router.get("/preview", response_model=dict)
def framework_preview(db: Session = Depends(get_db)) -> dict:
    """Public preview for the landing page: pillar names, the maturity scale and
    the question count. Question wording stays behind authentication."""
    from app.api.routes.frameworks import current_published_version
    from app.core.errors import APIError

    try:
        version = current_published_version(db)
    except APIError:
        return {"pillars": [], "levels": [], "question_count": 0}

    pillars = [
        {
            "code": axis.code,
            "name_ar": axis.name_ar,
            "name_en": axis.name_en,
            "question_count": len(axis.questions),
        }
        for axis in version.axes
    ]
    return {
        "pillars": pillars,
        "levels": [
            {
                "score": level.score,
                "label_ar": level.label_ar,
                "label_en": level.label_en,
                "description_ar": level.description_ar,
                "description_en": level.description_en,
            }
            for level in version.maturity_levels
        ],
        "question_count": sum(p["question_count"] for p in pillars),
    }


@router.get("/pillars", response_model=list[dict])
def list_pillars(db: Session = Depends(get_db)) -> list[dict]:
    """Kept for clients that only need the pillar list."""
    return framework_preview(db)["pillars"]
