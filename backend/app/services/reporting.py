"""Final report generation — BRD section 9.

The report is authored as HTML and printed through headless Chromium. That
choice is deliberate: the traditional Python PDF libraries break Arabic letter
shaping and bidirectional runs, while a browser engine renders Arabic and RTL
correctly and lets iValue restyle the template without touching code (FR-34).

All seven required sections are produced: cover, executive summary, maturity
results, axis-level findings, priority improvement areas, recommended
initiatives and the implementation roadmap.
"""

from __future__ import annotations

import html
import json
import logging
import math
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import utcnow
from app.models import Assessment, FrameworkVersion, Organization, ScoringRun
from app.models.initiatives import AIFinding, Initiative, RoadmapHorizon
from app.services import assessment_service

log = logging.getLogger("remas.reporting")

T = {
    "ar": {
        "report_title": "تقرير تقييم النضج المؤسسي",
        "confidential": "وثيقة سرّية — للاستخدام الداخلي لدى العميل و iValue Consult فقط.",
        "client": "المنشأة",
        "assessment": "التقييم",
        "version": "نسخة الإطار",
        "date": "تاريخ الإصدار",
        "scope": "نطاق التقييم",
        "scope_body": "يغطي هذا التقرير {axes} محوراً و{questions} سؤالاً من إطار {framework}.",
        "exec": "الملخص التنفيذي",
        "overall": "النتيجة الإجمالية",
        "level": "مستوى النضج",
        "completeness": "اكتمال الإجابات",
        "evidence": "اكتمال الأدلة",
        "results": "نتائج النضج",
        "by_axis": "النتيجة حسب المحور",
        "radar": "توزيع النضج",
        "heatmap": "الخريطة الحرارية",
        "axis_findings": "نتائج المحاور التفصيلية",
        "strengths": "نقاط القوة",
        "gaps": "الفجوات",
        "opportunities": "فرص التحسين",
        "priorities": "مجالات التحسين ذات الأولوية",
        "rank": "الترتيب",
        "axis": "المحور",
        "score": "الدرجة",
        "coverage": "التغطية",
        "priority_logic": "منطق الأولوية: حجم الفجوة، ووزن المحور، واكتمال الأدلة، والأهمية الاستراتيجية.",
        "initiatives": "المبادرات والمشاريع الموصى بها",
        "objective": "الهدف",
        "rationale": "المبرر",
        "owner": "الجهة المقترحة",
        "dependencies": "الاعتماديات",
        "horizon": "أفق التنفيذ",
        "roadmap": "خارطة طريق التنفيذ",
        "no_initiatives": "لم تُنتج مبادرات — تحتاج مكتبة المبادرات إلى تهيئة من iValue.",
        "not_scored": "لم تُحتسب",
        "page": "صفحة",
        "prepared_by": "أُعد بواسطة iValue Consult",
        "method": "منهجية الاحتساب",
        "method_body": "المتوسط المرجّح: مجموع (درجة السؤال × وزنه) ÷ مجموع الأوزان، ثم مجموع (درجة المحور × وزنه) ÷ مجموع أوزان المحاور. الأسئلة الموسومة «غير منطبق» مستبعدة من البسط والمقام. الاحتساب حتمي وقابل لإعادة الإنتاج من نسخة القواعد المجمّدة عند التقديم.",
        "ai_note": "الملاحظات التحليلية في هذا التقرير مسودات آلية خاضعة لمراجعة خبير iValue، ولا تغيّر أي درجة محتسبة.",
    },
    "en": {
        "report_title": "Institutional Maturity Assessment Report",
        "confidential": "Confidential — for the client and iValue Consult only.",
        "client": "Organisation",
        "assessment": "Assessment",
        "version": "Framework version",
        "date": "Issue date",
        "scope": "Assessment scope",
        "scope_body": "This report covers {axes} pillars and {questions} questions from the {framework} framework.",
        "exec": "Executive summary",
        "overall": "Overall score",
        "level": "Maturity level",
        "completeness": "Answer completeness",
        "evidence": "Evidence completeness",
        "results": "Maturity results",
        "by_axis": "Score by pillar",
        "radar": "Maturity distribution",
        "heatmap": "Heat map",
        "axis_findings": "Axis-level findings",
        "strengths": "Strengths",
        "gaps": "Gaps",
        "opportunities": "Improvement opportunities",
        "priorities": "Priority improvement areas",
        "rank": "Rank",
        "axis": "Pillar",
        "score": "Score",
        "coverage": "Coverage",
        "priority_logic": "Priority logic: maturity gap magnitude, axis weight, evidence completeness and strategic importance.",
        "initiatives": "Recommended initiatives / projects",
        "objective": "Objective",
        "rationale": "Rationale",
        "owner": "Suggested function",
        "dependencies": "Dependencies",
        "horizon": "Implementation horizon",
        "roadmap": "Implementation roadmap",
        "no_initiatives": "No initiatives were produced — the initiative library needs configuring by iValue.",
        "not_scored": "Not scored",
        "page": "Page",
        "prepared_by": "Prepared by iValue Consult",
        "method": "Calculation method",
        "method_body": "Weighted mean: sum(question score × weight) ÷ sum(weights), then sum(axis score × weight) ÷ sum(axis weights). Questions marked not applicable are excluded from both numerator and denominator. The calculation is deterministic and reproducible from the rule set frozen at submission.",
        "ai_note": "Analytical observations in this report are automated drafts subject to iValue expert review; they never alter a calculated score.",
    },
}

RAMP = ["#c9d2db", "#9db4cc", "#6d8fb2", "#426b95", "#1e3a5c"]


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def _pick(row: Any, field: str, locale: str) -> str:
    value = getattr(row, f"{field}_{locale}", None) or getattr(
        row, f"{field}_{'en' if locale == 'ar' else 'ar'}", None
    )
    return str(value or "")


def _radar_svg(points: list[tuple[str, float]], size: int = 340) -> str:
    if len(points) < 3:
        return ""
    pad, cx, cy = 38, size / 2, size / 2
    radius = size / 2 - pad

    def at(index: int, ratio: float) -> tuple[float, float]:
        angle = (2 * math.pi * index) / len(points) - math.pi / 2
        return cx + math.cos(angle) * radius * ratio, cy + math.sin(angle) * radius * ratio

    parts = [f'<svg viewBox="0 0 {size} {size}" width="{size}" height="{size}">']
    for ring in (0.25, 0.5, 0.75, 1.0):
        coords = " ".join(f"{x:.1f},{y:.1f}" for x, y in (at(i, ring) for i in range(len(points))))
        fill = "#f4f6f8" if ring == 1.0 else "none"
        parts.append(f'<polygon points="{coords}" fill="{fill}" stroke="#c6d0da" stroke-width="1"/>')
    for i in range(len(points)):
        x, y = at(i, 1)
        parts.append(f'<line x1="{cx}" y1="{cy}" x2="{x:.1f}" y2="{y:.1f}" stroke="#c6d0da"/>')
    coords = " ".join(
        f"{x:.1f},{y:.1f}"
        for x, y in (at(i, max(0.0, (v - 1) / 4)) for i, (_, v) in enumerate(points))
    )
    parts.append(
        f'<polygon points="{coords}" fill="#3d669033" stroke="#1e3a5c" stroke-width="2" stroke-linejoin="round"/>'
    )
    for i, (label, value) in enumerate(points):
        x, y = at(i, max(0.0, (value - 1) / 4))
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="#1e3a5c"/>')
        lx, ly = at(i, 1.16)
        parts.append(
            f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="8.5" fill="#6b7d8d" '
            f'text-anchor="middle" dominant-baseline="middle">{_esc(label)}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def build_context(db: Session, assessment: Assessment, locale: str = "ar") -> dict[str, Any]:
    org = db.get(Organization, assessment.organization_id)
    version = db.get(FrameworkVersion, assessment.framework_version_id)
    run = db.scalars(
        select(ScoringRun)
        .where(ScoringRun.assessment_id == assessment.id)
        .order_by(ScoringRun.created_at.desc())
    ).first()

    result = run.result if run and run.result else assessment_service.calculate(db, assessment).as_dict()
    axes = {a.id: a for a in assessment_service.selected_axes(db, assessment)}
    levels = {lv.score: lv for lv in (version.maturity_levels if version else [])}

    findings: dict[str, dict[str, list[AIFinding]]] = {}
    narrative: AIFinding | None = None
    for finding in db.scalars(
        select(AIFinding)
        .where(AIFinding.assessment_id == assessment.id, AIFinding.review_status != "rejected")
        .order_by(AIFinding.created_at.desc())
    ):
        if finding.kind == "narrative" and narrative is None:
            narrative = finding
        if finding.axis_id and finding.kind in ("strength", "gap", "opportunity"):
            bucket = findings.setdefault(finding.axis_id, {})
            bucket.setdefault(finding.kind, []).append(finding)

    horizons = list(
        db.scalars(
            select(RoadmapHorizon)
            .where(RoadmapHorizon.framework_version_id == assessment.framework_version_id)
            .order_by(RoadmapHorizon.order_index)
        )
    )
    initiatives = list(
        db.scalars(
            select(Initiative)
            .where(Initiative.assessment_id == assessment.id, Initiative.is_included.is_(True))
            .order_by(Initiative.priority, Initiative.order_index)
        )
    )

    return {
        "locale": locale,
        "t": T[locale],
        "org": org,
        "assessment": assessment,
        "version": version,
        "result": result,
        "axes": axes,
        "levels": levels,
        "findings": findings,
        "narrative": narrative,
        "horizons": horizons,
        "initiatives": initiatives,
        "generated_at": utcnow(),
    }


def render_html(ctx: dict[str, Any]) -> str:
    locale = ctx["locale"]
    t = ctx["t"]
    rtl = locale == "ar"
    result = ctx["result"]
    axes = ctx["axes"]
    levels = ctx["levels"]
    org = ctx["org"]

    def level_label(score: int | None) -> str:
        if not score or score not in levels:
            return "—"
        return _pick(levels[score], "label", locale)

    def axis_name(axis_id: str, fallback: str) -> str:
        axis = axes.get(axis_id)
        return _pick(axis, "name", locale) if axis else fallback

    scored = [a for a in result["axes"] if a["is_scored"] and a["score"] is not None]
    radar = [(a["code"], float(a["score"])) for a in scored]

    org_name = _pick(org, "name", locale) if org else ""
    total_questions = sum(a["total_questions"] for a in result["axes"])

    # ── cover ──────────────────────────────────────────────────────────────
    out = [f"""<!doctype html><html lang="{locale}" dir="{'rtl' if rtl else 'ltr'}"><head>
<meta charset="utf-8"><title>{_esc(t['report_title'])}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans+Arabic:wght@300;400;500;600;700&family=Readex+Pro:wght@400;500;600&display=swap">
<style>{_css(rtl)}</style></head><body>

<section class="cover">
  <div class="cover-mark"><i></i><i></i><i></i><i></i><i></i></div>
  <div class="eyebrow">REMAS · iValue Consult</div>
  <h1>{_esc(t['report_title'])}</h1>
  <table class="cover-meta">
    <tr><th>{_esc(t['client'])}</th><td>{_esc(org_name)}</td></tr>
    <tr><th>{_esc(t['assessment'])}</th><td>{_esc(ctx['assessment'].name)}</td></tr>
    <tr><th>{_esc(t['version'])}</th><td class="mono">{_esc(ctx['version'].version if ctx['version'] else '—')}</td></tr>
    <tr><th>{_esc(t['date'])}</th><td class="mono">{ctx['generated_at'].strftime('%Y-%m-%d')}</td></tr>
  </table>
  <div class="scope">
    <div class="label">{_esc(t['scope'])}</div>
    <p>{_esc(t['scope_body'].format(axes=len(result['axes']), questions=total_questions,
        framework=_pick(ctx['version'].framework, 'name', locale) if ctx['version'] else 'REMAS'))}</p>
  </div>
  <p class="confidential">{_esc(t['confidential'])}</p>
</section>
"""]

    # ── executive summary ─────────────────────────────────────────────────
    narrative = ctx["narrative"]
    body = _pick(narrative, "body", locale) if narrative else ""
    out.append(f"""<section class="page">
<h2>{_esc(t['exec'])}</h2>
<div class="tiles">
  <div class="tile hero"><span class="tile-v">{_num(result['overall_score'])}</span><span class="tile-l">{_esc(t['overall'])}</span></div>
  <div class="tile"><span class="tile-v">{_esc(level_label(result['maturity_level']))}</span><span class="tile-l">{_esc(t['level'])}</span></div>
  <div class="tile"><span class="tile-v">{round(result['completeness']*100)}%</span><span class="tile-l">{_esc(t['completeness'])}</span></div>
  <div class="tile"><span class="tile-v">{round(result['evidence_completeness']*100)}%</span><span class="tile-l">{_esc(t['evidence'])}</span></div>
</div>
{f'<p class="lede">{_esc(body)}</p>' if body else ''}
<div class="two-col">
  <div><h4>{_esc(t['strengths'])}</h4>{_chips(result['strengths'], axes, locale, 'ok')}</div>
  <div><h4>{_esc(t['gaps'])}</h4>{_chips(result['gaps'], axes, locale, 'bad')}</div>
</div>
<div class="note">{_esc(t['ai_note'])}</div>
</section>""")

    # ── maturity results ──────────────────────────────────────────────────
    rows = []
    for row in result["axes"]:
        pct = ((row["score"] - 1) / 4 * 100) if row["score"] is not None else 0
        colour = RAMP[(row["maturity_level"] or 1) - 1] if row["maturity_level"] else "#dbe2e9"
        rows.append(f"""<tr>
  <td class="mono dim">{_esc(row['code'])}</td>
  <td>{_esc(axis_name(row['axis_id'], row['code']))}</td>
  <td class="bar-cell"><span class="bar"><i style="width:{pct:.0f}%;background:{colour}"></i></span></td>
  <td class="mono num">{_num(row['score']) if row['is_scored'] else _esc(t['not_scored'])}</td>
  <td class="mono num dim">{round(row['coverage']*100)}%</td>
</tr>""")

    heat = "".join(
        f'<div class="heat-cell" style="background:{RAMP[(a["maturity_level"] or 1)-1] if a["maturity_level"] else "#eef2f6"};'
        f'color:{"#0f1b28" if (a["maturity_level"] or 1) <= 2 else "#fff"}">'
        f'<span class="hc">{_esc(a["code"])}</span><span class="hv">{_num(a["score"]) if a["is_scored"] else "—"}</span></div>'
        for a in result["axes"]
    )

    out.append(f"""<section class="page">
<h2>{_esc(t['results'])}</h2>
<div class="results-grid">
  <div>
    <h4>{_esc(t['by_axis'])}</h4>
    <table class="data">
      <thead><tr><th></th><th>{_esc(t['axis'])}</th><th></th><th class="num">{_esc(t['score'])}</th><th class="num">{_esc(t['coverage'])}</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
  </div>
  <div class="radar-wrap">
    <h4>{_esc(t['radar'])}</h4>
    {_radar_svg(radar)}
  </div>
</div>
<h4 class="mt">{_esc(t['heatmap'])}</h4>
<div class="heat">{heat}</div>
<div class="note"><b>{_esc(t['method'])}:</b> {_esc(t['method_body'])}</div>
</section>""")

    # ── axis-level findings ───────────────────────────────────────────────
    blocks = []
    for row in result["axes"]:
        axis_findings = ctx["findings"].get(row["axis_id"], {})

        def text(kind: str) -> str:
            items = axis_findings.get(kind) or []
            return _pick(items[0], "body", locale) if items else "—"

        colour = RAMP[(row["maturity_level"] or 1) - 1] if row["maturity_level"] else "#dbe2e9"
        blocks.append(f"""<div class="axis-block">
  <div class="axis-head">
    <span class="swatch" style="background:{colour}"></span>
    <span class="mono dim">{_esc(row['code'])}</span>
    <h4>{_esc(axis_name(row['axis_id'], row['code']))}</h4>
    <span class="axis-score mono">{_num(row['score']) if row['is_scored'] else _esc(t['not_scored'])}</span>
  </div>
  <dl>
    <dt>{_esc(t['strengths'])}</dt><dd>{_esc(text('strength'))}</dd>
    <dt>{_esc(t['gaps'])}</dt><dd>{_esc(text('gap'))}</dd>
    <dt>{_esc(t['opportunities'])}</dt><dd>{_esc(text('opportunity'))}</dd>
    <dt>{_esc(t['evidence'])}</dt><dd class="mono">{round(row['evidence_completeness']*100)}%</dd>
  </dl>
</div>""")
    out.append(f'<section class="page"><h2>{_esc(t["axis_findings"])}</h2>{"".join(blocks)}</section>')

    # ── priority improvement areas ────────────────────────────────────────
    prio_rows = "".join(
        f"""<tr><td class="mono num">{p['rank']}</td>
        <td class="mono dim">{_esc(p['code'])}</td>
        <td>{_esc(axis_name(p['axis_id'], p['code']))}</td>
        <td class="mono num">{_num(p['score'])}</td>
        <td class="mono num">{round((1-p['evidence_gap'])*100)}%</td>
        <td class="mono num">{_num(p['priority_score'])}</td></tr>"""
        for p in result["priorities"][:12]
    )
    out.append(f"""<section class="page">
<h2>{_esc(t['priorities'])}</h2>
<table class="data">
  <thead><tr><th class="num">{_esc(t['rank'])}</th><th></th><th>{_esc(t['axis'])}</th>
  <th class="num">{_esc(t['score'])}</th><th class="num">{_esc(t['evidence'])}</th><th class="num">Priority</th></tr></thead>
  <tbody>{prio_rows}</tbody>
</table>
<div class="note">{_esc(t['priority_logic'])}</div>
</section>""")

    # ── initiatives + roadmap ─────────────────────────────────────────────
    initiatives = ctx["initiatives"]
    horizons = ctx["horizons"]
    if initiatives:
        cards = "".join(
            f"""<div class="init">
  <div class="init-head">
    <span class="prio">P{i.priority}</span>
    <h4>{_esc(_pick(i, 'title', locale))}</h4>
    <span class="chip mono">{_esc(i.linked_gap or '')}</span>
  </div>
  <dl>
    <dt>{_esc(t['objective'])}</dt><dd>{_esc(_pick(i, 'objective', locale) or '—')}</dd>
    <dt>{_esc(t['rationale'])}</dt><dd>{_esc(_pick(i, 'rationale', locale) or '—')}</dd>
    <dt>{_esc(t['owner'])}</dt><dd>{_esc(_pick(i, 'owner_function', locale) or '—')}</dd>
    <dt>{_esc(t['dependencies'])}</dt><dd>{_esc(_pick(i, 'dependencies', locale) or '—')}</dd>
    <dt>{_esc(t['horizon'])}</dt><dd>{_esc(_horizon_name(horizons, i.horizon_code, locale))}</dd>
  </dl>
</div>"""
            for i in initiatives
        )
        lanes = []
        for horizon in horizons:
            items = [i for i in initiatives if i.horizon_code == horizon.code]
            lane_items = "".join(
                f'<li>{_esc(_pick(i, "title", locale))}</li>' for i in items
            ) or '<li class="dim">—</li>'
            lanes.append(f"""<div class="lane">
  <div class="lane-head"><b>{_esc(_pick(horizon, 'name', locale))}</b>
  <span class="mono dim">{horizon.months_from}–{horizon.months_to}m</span></div>
  <ul>{lane_items}</ul>
</div>""")
        out.append(
            f'<section class="page"><h2>{_esc(t["initiatives"])}</h2>{cards}</section>'
            f'<section class="page"><h2>{_esc(t["roadmap"])}</h2><div class="lanes">{"".join(lanes)}</div></section>'
        )
    else:
        out.append(
            f'<section class="page"><h2>{_esc(t["initiatives"])}</h2>'
            f'<div class="note">{_esc(t["no_initiatives"])}</div></section>'
        )

    out.append(f'<footer class="doc-footer">{_esc(t["prepared_by"])}</footer></body></html>')
    return "".join(out)


def _horizon_name(horizons, code: str | None, locale: str) -> str:
    for horizon in horizons:
        if horizon.code == code:
            return _pick(horizon, "name", locale)
    return code or "—"


def _num(value: Any) -> str:
    if value is None:
        return "—"
    return f"{float(value):.2f}".rstrip("0").rstrip(".")


def _chips(ids: list[str], axes: dict, locale: str, tone: str) -> str:
    if not ids:
        return '<span class="dim">—</span>'
    return "".join(
        f'<span class="chip {tone}">{_esc(_pick(axes[i], "name", locale) if i in axes else i)}</span>'
        for i in ids
    )


def _css(rtl: bool) -> str:
    return """
@page { size: A4; margin: 16mm 14mm 18mm; }
* { box-sizing: border-box; }
body { font-family: "IBM Plex Sans Arabic","IBM Plex Sans",sans-serif; color:#0f1b28;
  font-size: 10.5pt; line-height: 1.65; margin:0; }
h1,h2,h3,h4 { font-family:"Readex Pro","IBM Plex Sans Arabic",sans-serif; margin:0; font-weight:600; }
h2 { font-size: 15pt; padding-bottom:6px; border-bottom:2px solid #1e3a5c; margin-bottom:14px; }
h4 { font-size: 10.5pt; margin-bottom:6px; }
.mono { font-family:"IBM Plex Mono",monospace; font-variant-numeric: tabular-nums; }
.dim { color:#6b7d8d; }
.num { text-align:end; }
.mt { margin-top:16px; }
section.page { page-break-before: always; padding-top:2mm; }
.cover { min-height: 250mm; display:flex; flex-direction:column; justify-content:center; }
.cover-mark { display:flex; align-items:flex-end; gap:4px; height:40px; margin-bottom:22px; }
.cover-mark i { width:7px; border-radius:2px; display:block; }
.cover-mark i:nth-child(1){height:30%;background:#c9d2db}
.cover-mark i:nth-child(2){height:47%;background:#9db4cc}
.cover-mark i:nth-child(3){height:64%;background:#6d8fb2}
.cover-mark i:nth-child(4){height:82%;background:#426b95}
.cover-mark i:nth-child(5){height:100%;background:#1e3a5c}
.eyebrow { font-family:"IBM Plex Mono",monospace; font-size:8pt; letter-spacing:.18em;
  text-transform:uppercase; color:#6b7d8d; }
.cover h1 { font-size:26pt; margin:10px 0 26px; letter-spacing:-.02em; }
.cover-meta { border-collapse:collapse; width:100%; max-width:150mm; }
.cover-meta th { text-align:start; font-weight:500; color:#6b7d8d; font-size:9pt;
  padding:7px 0; width:38mm; border-bottom:1px solid #dbe2e9; }
.cover-meta td { padding:7px 0; border-bottom:1px solid #dbe2e9; }
.scope { margin-top:26px; padding:12px 14px; background:#f6f8fa; border:1px solid #dbe2e9; border-radius:6px; }
.scope .label { font-size:8.5pt; color:#6b7d8d; margin-bottom:3px; }
.scope p { margin:0; font-size:10pt; }
.confidential { margin-top:auto; padding-top:22px; font-size:8.5pt; color:#6b7d8d; }
.tiles { display:grid; grid-template-columns:repeat(4,1fr); gap:8px; margin-bottom:14px; }
.tile { border:1px solid #dbe2e9; border-radius:6px; padding:10px 12px; }
.tile.hero { border-color:#88a9cc; background:#f4f8fc; }
.tile-v { display:block; font-family:"Readex Pro",sans-serif; font-size:17pt; line-height:1.1;
  font-variant-numeric:tabular-nums; }
.tile.hero .tile-v { color:#1e3a5c; }
.tile-l { display:block; font-size:8pt; color:#6b7d8d; margin-top:3px; }
.lede { font-size:10.5pt; margin:10px 0 14px; }
.two-col { display:grid; grid-template-columns:1fr 1fr; gap:14px; margin:12px 0; }
.chip { display:inline-block; font-size:8.5pt; padding:2px 9px; border-radius:99px;
  border:1px solid #dbe2e9; background:#f6f8fa; margin:0 0 4px; }
.chip.ok { background:#dcefe4; border-color:#a8d3bd; color:#1f6b4a; }
.chip.bad { background:#f8e2dc; border-color:#e0b4a6; color:#9b3d2e; }
.note { margin-top:12px; padding:9px 12px; background:#f4f8fc; border:1px solid #dbe6f2;
  border-radius:5px; font-size:9pt; color:#3f5162; }
table.data { width:100%; border-collapse:collapse; font-size:9.5pt; }
table.data th { text-align:start; font-size:8.5pt; color:#6b7d8d; font-weight:600;
  background:#f6f8fa; padding:6px 8px; border-bottom:1px solid #dbe2e9; }
table.data td { padding:5px 8px; border-bottom:1px solid #eef2f6; }
.bar-cell { width:34mm; }
.bar { display:block; height:7px; background:#eef2f6; border-radius:99px; overflow:hidden; }
.bar i { display:block; height:100%; border-radius:99px; }
.results-grid { display:grid; grid-template-columns:1fr 92mm; gap:14px; align-items:start; }
.radar-wrap svg { width:100%; height:auto; }
.heat { display:grid; grid-template-columns:repeat(8,1fr); gap:4px; }
.heat-cell { border-radius:5px; padding:6px 7px; min-height:15mm; display:flex;
  flex-direction:column; justify-content:space-between; }
.heat-cell .hc { font-family:"IBM Plex Mono",monospace; font-size:7pt; opacity:.85; }
.heat-cell .hv { font-family:"IBM Plex Mono",monospace; font-size:11pt; font-weight:500; }
.axis-block { border:1px solid #dbe2e9; border-radius:6px; padding:11px 13px; margin-bottom:9px;
  page-break-inside: avoid; }
.axis-head { display:flex; align-items:center; gap:8px; margin-bottom:7px; }
.axis-head h4 { flex:1; }
.swatch { width:10px; height:10px; border-radius:2px; display:inline-block; }
.axis-score { font-size:12pt; font-weight:500; }
dl { margin:0; display:grid; grid-template-columns:32mm 1fr; gap:3px 10px; font-size:9.5pt; }
dt { color:#6b7d8d; font-size:9pt; }
dd { margin:0; }
.init { border:1px solid #dbe2e9; border-radius:6px; padding:11px 13px; margin-bottom:9px;
  page-break-inside: avoid; }
.init-head { display:flex; align-items:center; gap:8px; margin-bottom:7px; }
.init-head h4 { flex:1; }
.prio { font-family:"IBM Plex Mono",monospace; font-size:8.5pt; background:#1e3a5c; color:#fff;
  padding:2px 7px; border-radius:4px; }
.lanes { display:grid; grid-template-columns:repeat(4,1fr); gap:8px; }
.lane { border:1px solid #dbe2e9; border-radius:6px; overflow:hidden; }
.lane-head { background:#f6f8fa; padding:7px 9px; border-bottom:1px solid #dbe2e9; font-size:9pt;
  display:flex; justify-content:space-between; gap:6px; }
.lane ul { margin:0; padding:8px 9px; padding-inline-start:20px; font-size:9pt; }
.lane li { margin-bottom:4px; }
.doc-footer { margin-top:16px; padding-top:8px; border-top:1px solid #dbe2e9;
  font-size:8.5pt; color:#6b7d8d; }
"""


# ────────────────────────────── PDF rendering ───────────────────────────────


def render_pdf(html_text: str, out_path: Path) -> Path:
    """Print the HTML through headless Chromium.

    Chosen over the Python PDF libraries because those break Arabic letter
    shaping and bidi ordering; a browser engine gets both right.
    """
    from playwright.sync_api import sync_playwright

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content(html_text, wait_until="networkidle")
            page.pdf(
                path=str(out_path),
                format="A4",
                print_background=True,
                margin={"top": "16mm", "bottom": "18mm", "left": "14mm", "right": "14mm"},
            )
        finally:
            browser.close()
    return out_path


def structured_export(ctx: dict[str, Any]) -> dict[str, Any]:
    """The exportable structured data the BRD asks for alongside the PDF."""
    locale = ctx["locale"]
    axes = ctx["axes"]
    return {
        "organisation": {
            "id": ctx["org"].id if ctx["org"] else None,
            "name_ar": ctx["org"].name_ar if ctx["org"] else None,
            "name_en": ctx["org"].name_en if ctx["org"] else None,
        },
        "assessment": {
            "id": ctx["assessment"].id,
            "name": ctx["assessment"].name,
            "layer": ctx["assessment"].layer,
            "status": ctx["assessment"].status,
            "submitted_at": ctx["assessment"].submitted_at.isoformat()
            if ctx["assessment"].submitted_at
            else None,
        },
        "framework_version": {
            "id": ctx["version"].id if ctx["version"] else None,
            "version": ctx["version"].version if ctx["version"] else None,
            "scoring_config": ctx["version"].scoring_config if ctx["version"] else {},
        },
        "scoring": ctx["result"],
        "axis_names": {
            axis_id: {"ar": axis.name_ar, "en": axis.name_en} for axis_id, axis in axes.items()
        },
        "initiatives": [
            {
                "title_ar": i.title_ar,
                "title_en": i.title_en,
                "axis_id": i.axis_id,
                "priority": i.priority,
                "horizon": i.horizon_code,
                "linked_gap": i.linked_gap,
                "source": i.source,
            }
            for i in ctx["initiatives"]
        ],
        "generated_at": ctx["generated_at"].isoformat(),
        "locale": locale,
    }


def report_path(assessment_id: str, locale: str, fmt: str) -> Path:
    return settings.storage_dir / "reports" / f"{assessment_id}_{locale}.{fmt}"


def generate(
    db: Session, assessment: Assessment, locale: str = "ar", fmt: str = "pdf"
) -> tuple[Path | str, dict[str, Any]]:
    ctx = build_context(db, assessment, locale)
    if fmt == "json":
        return json.dumps(structured_export(ctx), ensure_ascii=False, indent=2), ctx
    html_text = render_html(ctx)
    if fmt == "html":
        return html_text, ctx
    return render_pdf(html_text, report_path(assessment.id, locale, "pdf")), ctx
