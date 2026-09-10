"""The AI pipeline — AI-01 through AI-07.

Five stages, each with its own acceptance criterion:

  1. extract     AI-01  text + metadata from every uploaded document
  2. relevance   AI-02  does the evidence actually cover the question?
  3. explain     AI-03  every finding cites document + page + excerpt
  4. analyse     AI-04  strengths, gaps, narratives per axis and overall
  5. recommend   AI-05/06 initiatives drawn from the library, phased into horizons

Governing rule, from FR-26: **the AI proposes and explains; it never calculates
and never approves.** Scores come only from `services/scoring.py`; nothing in
this module writes a score.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import utcnow
from app.models import (
    Assessment,
    Axis,
    Document,
    DocumentLink,
    EvidenceStatus,
    Question,
    Response,
    User,
)
from app.models.initiatives import AIFinding, AIJob, Initiative, InitiativeTemplate, RoadmapHorizon
from app.services import assessment_service
from app.services.ai import extraction
from app.services import evidence_store
from app.services.ai import config as ai_config
from app.services.ai.provider import PROMPT_VERSION, BaseProvider, RuleProvider, get_provider

log = logging.getLogger("remas.ai.pipeline")

# Coverage verdicts the relevance stage may propose. Deliberately conservative:
# an uncertain match becomes "requires clarification", never "rejected" — a
# wrongly rejected document costs the customer far more than a second look.
COVERAGE_COVERED = "covered"
COVERAGE_PARTIAL = "partial"
COVERAGE_UNCLEAR = "unclear"
COVERAGE_MISSING = "missing"


def _keywords(text: str, limit: int = 12) -> list[str]:
    stop = {
        "the", "and", "for", "with", "that", "this", "are", "was", "from", "have",
        "has", "does", "your", "there", "shall", "system", "organisation", "organization",
        "من", "في", "على", "إلى", "عن", "هل", "التي", "الذي", "هذه", "هذا", "مع",
        "أو", "ما", "مدى", "يوجد", "توجد", "كيف", "كل", "بين", "عند", "قبل", "بعد",
    }
    words = [w.strip("؟?،,.:()[]\"'").lower() for w in text.split()]
    seen: list[str] = []
    for word in words:
        if len(word) < 4 or word in stop or word in seen:
            continue
        seen.append(word)
        if len(seen) >= limit:
            break
    return seen


# ─────────────────────────── stage 1: extraction ───────────────────────────


def extract_document(db: Session, document: Document) -> dict[str, Any]:
    """AI-01. Idempotent — re-running reuses the stored extraction."""
    if document.extraction and not document.extraction.get("error"):
        return document.extraction

    result = extraction.extract(
        document.stored_path,
        document.content_type,
        loader=lambda: evidence_store.read(document),
        ocr_config=ai_config.resolve(db),
    )
    document.extraction = result
    db.flush()
    return result


# ─────────────────────── stage 2 + 3: relevance & citation ──────────────────


def _assess_coverage(
    question: Question, doc_result: dict[str, Any]
) -> tuple[str, float, dict | None, list[str]]:
    """Compare a document's text against what the question asks for.

    Returns (verdict, confidence, citation, matched_terms)."""
    pages = doc_result.get("pages") or []
    text = (doc_result.get("text") or "").lower()

    if doc_result.get("ocr_required"):
        return COVERAGE_UNCLEAR, 0.2, None, []
    if not text:
        return COVERAGE_MISSING, 0.5, None, []

    expected = " ".join(
        filter(
            None,
            [
                question.text_ar,
                question.text_en,
                question.evidence_hint_ar,
                question.evidence_hint_en,
            ],
        )
    )
    terms = _keywords(expected)
    matched = [term for term in terms if term in text]
    ratio = len(matched) / len(terms) if terms else 0.0

    citation = None
    if matched:
        citation = extraction.excerpt(pages, matched[0])

    if ratio >= 0.4:
        return COVERAGE_COVERED, min(0.5 + ratio / 2, 0.95), citation, matched
    if ratio >= 0.15:
        return COVERAGE_PARTIAL, 0.45 + ratio, citation, matched
    return COVERAGE_UNCLEAR, 0.3, citation, matched


COVERAGE_TEXT = {
    COVERAGE_COVERED: (
        "يغطّي المستند المرفق العناصر المتوقعة لهذا السؤال.",
        "The attached document covers the elements expected for this question.",
    ),
    COVERAGE_PARTIAL: (
        "يغطّي المستند جزءاً من المتوقع؛ يُرجى إرفاق ما يوثّق باقي العناصر.",
        "The document covers part of what is expected; please attach evidence for the remainder.",
    ),
    COVERAGE_UNCLEAR: (
        "تعذّر التأكد من تغطية المستند لهذا السؤال — يحتاج توضيحاً من المراجع.",
        "Coverage could not be confirmed — this needs a reviewer's clarification.",
    ),
    COVERAGE_MISSING: (
        "لا يوجد نص قابل للقراءة في المستند المرفق.",
        "The attached document contains no readable text.",
    ),
}

VERDICT_TO_STATUS = {
    COVERAGE_COVERED: EvidenceStatus.AI_REVIEWED,
    COVERAGE_PARTIAL: EvidenceStatus.REQUIRES_CLARIFICATION,
    COVERAGE_UNCLEAR: EvidenceStatus.REQUIRES_CLARIFICATION,
    COVERAGE_MISSING: EvidenceStatus.REQUIRES_CLARIFICATION,
}


def review_evidence(db: Session, assessment: Assessment, job: AIJob) -> list[AIFinding]:
    """AI-02 + AI-03. Every finding carries document, page and excerpt."""
    links = list(
        db.scalars(select(DocumentLink).where(DocumentLink.assessment_id == assessment.id))
    )
    findings: list[AIFinding] = []

    for link in links:
        document = db.get(Document, link.document_id)
        question = db.get(Question, link.question_id)
        if document is None or question is None:
            continue

        result = extract_document(db, document)
        verdict, confidence, citation, matched = _assess_coverage(question, result)
        body_ar, body_en = COVERAGE_TEXT[verdict]

        finding = AIFinding(
            job_id=job.id,
            assessment_id=assessment.id,
            axis_id=question.axis_id,
            question_id=question.id,
            document_id=document.id,
            kind="evidence_coverage",
            severity="info" if verdict == COVERAGE_COVERED else "medium",
            title_ar=f"تغطية الدليل — {question.code}",
            title_en=f"Evidence coverage — {question.code}",
            body_ar=body_ar,
            body_en=body_en,
            confidence=round(confidence, 2),
            citation={
                "document_id": document.id,
                "filename": document.filename,
                "page": (citation or {}).get("page"),
                "excerpt": (citation or {}).get("excerpt"),
                "matched_terms": matched[:6],
                "verdict": verdict,
                "ocr_required": bool(result.get("ocr_required")),
                "language": result.get("language_hint"),
            },
        )
        db.add(finding)
        findings.append(finding)

        # The AI only proposes a status; a reviewer's explicit decision wins.
        if link.status in (EvidenceStatus.UPLOADED, EvidenceStatus.MISSING):
            link.status = VERDICT_TO_STATUS[verdict]

    db.flush()
    return findings


# ───────────────────────────── stage 4: analysis ────────────────────────────

ANALYSIS_SYSTEM = """You are a real-estate institutional-maturity assessor working for iValue Consult.
You are given the deterministic scoring result of one assessment. You must NOT
recalculate, adjust or contradict any score — treat every number as final.
Write concise, factual, board-ready observations in BOTH Arabic and English.
Return ONLY valid JSON matching the requested schema."""


def _analysis_prompt(context: dict[str, Any]) -> str:
    import json as _json

    return (
        "Assessment scoring result:\n"
        + _json.dumps(context, ensure_ascii=False, indent=2)
        + """

Return JSON:
{
  "axes": [
    {"axis_id": "...", "strengths_ar": "...", "strengths_en": "...",
     "gaps_ar": "...", "gaps_en": "...",
     "opportunities_ar": "...", "opportunities_en": "..."}
  ],
  "overall": {"narrative_ar": "...", "narrative_en": "...",
              "management_message_ar": "...", "management_message_en": "..."}
}
Every string: 1-3 sentences, specific to the scores given, no filler."""
    )


def _rule_axis_narrative(axis: Axis, row: dict[str, Any], level_labels: dict[int, tuple[str, str]]):
    score = row.get("score")
    level = row.get("maturity_level") or 1
    label_ar, label_en = level_labels.get(level, ("—", "—"))
    coverage = round((row.get("coverage") or 0) * 100)
    evidence = round((row.get("evidence_completeness") or 0) * 100)

    if score is None:
        return (
            f"لم تُحتسب نتيجة {axis.name_ar} لعدم كفاية الإجابات.",
            f"{axis.name_en} was not scored — insufficient answers.",
            "أكمل الإجابات المطلوبة لهذا المحور.",
            "Complete the required answers for this pillar.",
            "لا يمكن تحديد فرص التحسين قبل اكتمال الإجابات.",
            "Improvement opportunities cannot be identified until answers are complete.",
        )

    if score >= 4:
        s_ar = f"يقع {axis.name_ar} في مستوى «{label_ar}» بدرجة {score}، ما يعكس ممارسات منهجية ومتابعة منتظمة."
        s_en = f"{axis.name_en} sits at «{label_en}» with a score of {score}, reflecting systematic practices under regular monitoring."
        g_ar = f"الفجوة المتبقّية محدودة وتتركّز في الانتقال من المتابعة الدورية إلى القياس المستمر. اكتمال الأدلة {evidence}%."
        g_en = f"The remaining gap is limited and centres on moving from periodic monitoring to continuous measurement. Evidence completeness {evidence}%."
        o_ar = "ترسيخ القياس المستمر وربط مؤشرات المحور بلوحة الأداء المؤسسية."
        o_en = "Embed continuous measurement and link this pillar's indicators to the corporate performance dashboard."
    elif score >= 3:
        s_ar = f"يقع {axis.name_ar} في مستوى «{label_ar}» بدرجة {score}، مع وجود أساس منظّم يمكن البناء عليه."
        s_en = f"{axis.name_en} sits at «{label_en}» with a score of {score}, on an organised base that can be built upon."
        g_ar = f"التطبيق منظّم جزئياً وتظهر فجوات في الانتظام والتوثيق. اكتمال الأدلة {evidence}% وتغطية الإجابات {coverage}%."
        g_en = f"Implementation is partly organised with gaps in consistency and documentation. Evidence completeness {evidence}%, answer coverage {coverage}%."
        o_ar = "توحيد الإجراءات وتوثيقها واعتماد دورية مراجعة معلنة."
        o_en = "Standardise and document the procedures, and adopt a published review cycle."
    else:
        s_ar = f"يوفّر {axis.name_ar} نقطة انطلاق واضحة للتحسين رغم الدرجة المنخفضة ({score})."
        s_en = f"{axis.name_en} offers a clear starting point for improvement despite the low score ({score})."
        g_ar = f"مستوى «{label_ar}»: الممارسات متفرقة وغير موثّقة، واكتمال الأدلة {evidence}%. هذا المحور يمثّل أولوية تحسين."
        g_en = f"«{label_en}»: practices are scattered and undocumented, evidence completeness {evidence}%. This pillar is an improvement priority."
        o_ar = "تأسيس السياسة والإجراء الأساسيين وتعيين مالك واضح للمحور."
        o_en = "Establish the core policy and procedure and assign a clear owner for this pillar."

    return s_ar, s_en, g_ar, g_en, o_ar, o_en


def analyse(
    db: Session, assessment: Assessment, job: AIJob, provider: BaseProvider
) -> list[AIFinding]:
    """AI-04 — strengths, gaps, opportunities and narratives."""
    result = assessment_service.calculate(db, assessment)
    axes = {a.id: a for a in assessment_service.selected_axes(db, assessment)}

    from app.models import FrameworkVersion

    version = db.get(FrameworkVersion, assessment.framework_version_id)
    level_labels = {
        level.score: (level.label_ar, level.label_en)
        for level in (version.maturity_levels if version else [])
    } or {i: ("—", "—") for i in range(1, 6)}

    rows = {row["axis_id"]: row for row in result.as_dict()["axes"]}

    llm_axes: dict[str, dict] = {}
    llm_overall: dict[str, str] = {}
    if not isinstance(provider, RuleProvider):
        context = {
            "overall_score": result.overall_score,
            "maturity_level": result.maturity_level,
            "axes": [
                {
                    "axis_id": axis_id,
                    "code": row["code"],
                    "name_ar": axes[axis_id].name_ar if axis_id in axes else row["code"],
                    "name_en": axes[axis_id].name_en if axis_id in axes else row["code"],
                    "score": row["score"],
                    "maturity_level": row["maturity_level"],
                    "coverage": row["coverage"],
                    "evidence_completeness": row["evidence_completeness"],
                }
                for axis_id, row in rows.items()
            ],
        }
        try:
            payload = provider.complete_json(ANALYSIS_SYSTEM, _analysis_prompt(context))
            if isinstance(payload, dict):
                for item in payload.get("axes", []) or []:
                    if isinstance(item, dict) and item.get("axis_id"):
                        llm_axes[item["axis_id"]] = item
                if isinstance(payload.get("overall"), dict):
                    llm_overall = payload["overall"]
        except Exception as exc:  # noqa: BLE001 — never let the model break the run
            log.warning("analysis stage fell back to rules: %s", exc)
            job.error = f"analysis_llm_failed: {type(exc).__name__}"

    findings: list[AIFinding] = []
    for axis_id, row in rows.items():
        axis = axes.get(axis_id)
        if axis is None:
            continue
        s_ar, s_en, g_ar, g_en, o_ar, o_en = _rule_axis_narrative(axis, row, level_labels)
        override = llm_axes.get(axis_id, {})

        for kind, title, (text_ar, text_en), severity in (
            ("strength", ("نقاط القوة", "Strengths"),
             (override.get("strengths_ar") or s_ar, override.get("strengths_en") or s_en), "info"),
            ("gap", ("الفجوات", "Gaps"),
             (override.get("gaps_ar") or g_ar, override.get("gaps_en") or g_en),
             "high" if (row.get("score") or 5) < 2.5 else "medium"),
            ("opportunity", ("فرص التحسين", "Improvement opportunities"),
             (override.get("opportunities_ar") or o_ar, override.get("opportunities_en") or o_en), "info"),
        ):
            finding = AIFinding(
                job_id=job.id,
                assessment_id=assessment.id,
                axis_id=axis_id,
                kind=kind,
                severity=severity,
                title_ar=f"{title[0]} — {axis.name_ar}",
                title_en=f"{title[1]} — {axis.name_en}",
                body_ar=text_ar,
                body_en=text_en,
                confidence=0.7,
                citation={"axis_code": axis.code, "score": row.get("score"),
                          "basis": "scoring_run", "generated_by": provider.info.name},
            )
            db.add(finding)
            findings.append(finding)

    overall_ar = llm_overall.get("narrative_ar") or _overall_narrative(result, level_labels, "ar")
    overall_en = llm_overall.get("narrative_en") or _overall_narrative(result, level_labels, "en")
    summary = AIFinding(
        job_id=job.id,
        assessment_id=assessment.id,
        kind="narrative",
        severity="info",
        title_ar="الملخص التنفيذي",
        title_en="Executive summary",
        body_ar=overall_ar,
        body_en=overall_en,
        confidence=0.7,
        citation={"basis": "scoring_run", "overall_score": result.overall_score,
                  "generated_by": provider.info.name},
    )
    db.add(summary)
    findings.append(summary)
    db.flush()
    return findings


def _overall_narrative(result, level_labels: dict[int, tuple[str, str]], locale: str) -> str:
    score = result.overall_score
    level = result.maturity_level
    label = level_labels.get(level or 1, ("—", "—"))[0 if locale == "ar" else 1]
    scored = [a for a in result.axes if a.is_scored and a.score is not None]
    if not scored or score is None:
        return (
            "لم تكتمل الإجابات بما يكفي لإصدار نتيجة كلية."
            if locale == "ar"
            else "Answers are not complete enough to produce an overall result."
        )
    strongest = max(scored, key=lambda a: a.score)
    weakest = min(scored, key=lambda a: a.score)
    completeness = round(result.completeness * 100)
    evidence = round(result.evidence_completeness * 100)

    if locale == "ar":
        return (
            f"بلغت النتيجة الإجمالية {score} من 5، ما يضع المنشأة في مستوى «{label}». "
            f"أعلى المحاور أداءً {strongest.code} بدرجة {strongest.score}، وأدناها {weakest.code} بدرجة {weakest.score}. "
            f"اكتمال الإجابات {completeness}% واكتمال الأدلة {evidence}%، وهما يحدّان من دقة القراءة حيثما انخفضا. "
            f"التركيز المقترح للمرحلة القادمة على المحاور ذات الفجوة الأكبر والوزن الأعلى."
        )
    return (
        f"The overall score is {score} out of 5, placing the organisation at «{label}». "
        f"The strongest pillar is {strongest.code} at {strongest.score}; the weakest is {weakest.code} at {weakest.score}. "
        f"Answer completeness is {completeness}% and evidence completeness {evidence}% — where these are low, confidence in the reading is correspondingly lower. "
        f"The suggested focus is the pillars combining the largest gap with the highest weight."
    )


# ───────────────────── stage 5: initiatives & roadmap ───────────────────────


def recommend(db: Session, assessment: Assessment, job: AIJob) -> list[Initiative]:
    """AI-05 + AI-06. Initiatives come from iValue's approved library, matched to
    the axis and its maturity band, then phased into configured horizons.

    Nothing is invented: an initiative with no library match is not produced, so
    every recommendation is traceable to approved content (FR-28)."""
    result = assessment_service.calculate(db, assessment)
    axes = {a.id: a for a in assessment_service.selected_axes(db, assessment)}
    rows = {row["axis_id"]: row for row in result.as_dict()["axes"]}
    priorities = {p["axis_id"]: p for p in result.priorities}

    horizons = list(
        db.scalars(
            select(RoadmapHorizon)
            .where(RoadmapHorizon.framework_version_id == assessment.framework_version_id)
            .order_by(RoadmapHorizon.order_index)
        )
    )
    horizon_codes = [h.code for h in horizons] or ["immediate", "short", "medium", "long"]

    templates = list(
        db.scalars(
            select(InitiativeTemplate).where(
                InitiativeTemplate.framework_version_id == assessment.framework_version_id,
                InitiativeTemplate.is_active.is_(True),
            )
        )
    )

    # Clear previous engine output; reviewer-authored items survive (FR-30).
    for existing in db.scalars(
        select(Initiative).where(
            Initiative.assessment_id == assessment.id, Initiative.source != "reviewer"
        )
    ):
        db.delete(existing)
    db.flush()

    created: list[Initiative] = []
    ranked = sorted(
        (a for a in rows.values() if a.get("is_scored") and a.get("score") is not None),
        key=lambda r: priorities.get(r["axis_id"], {}).get("rank", 999),
    )

    for order, row in enumerate(ranked):
        axis = axes.get(row["axis_id"])
        if axis is None:
            continue
        score = float(row["score"])
        matches = [
            tpl
            for tpl in templates
            if (tpl.axis_id in (None, axis.id))
            and tpl.applies_min_score <= score <= tpl.applies_max_score
        ]
        if not matches:
            continue

        rank = priorities.get(axis.id, {}).get("rank", order + 1)
        # Highest-priority gaps land in the earliest horizon.
        bucket = 0 if rank <= 3 else 1 if rank <= 6 else 2 if rank <= 10 else 3
        horizon = horizon_codes[min(bucket, len(horizon_codes) - 1)]

        for match in matches[:2]:
            initiative = Initiative(
                assessment_id=assessment.id,
                axis_id=axis.id,
                template_id=match.id,
                title_ar=match.title_ar,
                title_en=match.title_en,
                objective_ar=match.objective_ar,
                objective_en=match.objective_en,
                rationale_ar=match.rationale_ar
                or f"درجة المحور {score} من 5 وترتيب الأولوية {rank}.",
                rationale_en=match.rationale_en
                or f"Pillar score {score} of 5, priority rank {rank}.",
                owner_function_ar=match.owner_function_ar,
                owner_function_en=match.owner_function_en,
                dependencies_ar=match.dependencies_ar,
                dependencies_en=match.dependencies_en,
                linked_gap=f"{axis.code} · score {score}",
                horizon_code=match.default_horizon_code or horizon,
                priority=min(rank, 5),
                order_index=len(created),
                source="engine",
            )
            db.add(initiative)
            created.append(initiative)

    db.flush()
    return created


# ────────────────────────────── orchestration ───────────────────────────────


def run(
    db: Session, assessment: Assessment, *, actor: User | None = None, stages: list[str] | None = None
) -> AIJob:
    """Run the pipeline end to end and record it as one auditable job."""
    wanted = set(stages or ["extract", "relevance", "analyse", "recommend"])
    provider = get_provider(db)

    job = AIJob(
        assessment_id=assessment.id,
        stage="+".join(sorted(wanted)),
        status="running",
        provider=provider.info.name,
        model=provider.info.model,
        prompt_version=PROMPT_VERSION,
        started_at=utcnow(),
        triggered_by_id=actor.id if actor else None,
    )
    db.add(job)
    db.flush()

    summary: dict[str, Any] = {}
    try:
        if "extract" in wanted:
            documents = list(
                db.scalars(
                    select(Document)
                    .join(DocumentLink, DocumentLink.document_id == Document.id)
                    .where(DocumentLink.assessment_id == assessment.id)
                    .distinct()
                )
            )
            extracted = 0
            needs_ocr = 0
            for document in documents:
                out = extract_document(db, document)
                extracted += 1
                needs_ocr += 1 if out.get("ocr_required") else 0
            summary["documents_extracted"] = extracted
            summary["documents_needing_ocr"] = needs_ocr

        if "relevance" in wanted:
            summary["evidence_findings"] = len(review_evidence(db, assessment, job))

        if "analyse" in wanted:
            summary["analysis_findings"] = len(analyse(db, assessment, job, provider))

        if "recommend" in wanted:
            summary["initiatives"] = len(recommend(db, assessment, job))

        job.status = "completed"
    except Exception as exc:  # noqa: BLE001
        log.exception("AI pipeline failed")
        job.status = "failed"
        job.error = f"{type(exc).__name__}: {exc}"
    finally:
        job.finished_at = utcnow()
        job.summary = summary
        db.flush()

    return job


def unanswered_context(db: Session, assessment: Assessment) -> list[Response]:
    return list(db.scalars(select(Response).where(Response.assessment_id == assessment.id)))
