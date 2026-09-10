"""HTML rendering for the final report — BRD section 9.

Pure: give it a context dictionary and it returns a document. It knows nothing
about the database, the ORM or the web framework, which is what makes the
seven required sections testable and previewable against a fixture rather than
only through a full assessment.

The report is authored as HTML and printed through headless Chromium (see
`pdf.py`). That choice is deliberate: the traditional Python PDF libraries
break Arabic letter shaping and bidirectional runs, while a browser engine
renders Arabic and RTL correctly and lets iValue restyle the template without
touching code (FR-34).
"""

from __future__ import annotations

import html
import math
from typing import Any

from app.services.reporting.styles import render_stylesheet

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
        "comparison": "المقارنة بالتقييم السابق",
        "previous": "السابق",
        "current": "الحالي",
        "change": "التغيّر",
        "no_prior": "لا يوجد تقييم سابق للمقارنة.",
        "criteria": "معايير التقييم",
        "improved": "تحسّن",
        "declined": "تراجع",
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
        "comparison": "Comparison with the previous assessment",
        "previous": "Previous",
        "current": "Current",
        "change": "Change",
        "no_prior": "No prior assessment is available for comparison.",
        "criteria": "Assessment criteria",
        "improved": "improved",
        "declined": "declined",
    },
}

RAMP = ["#c9d2db", "#9db4cc", "#6d8fb2", "#426b95", "#1e3a5c"]


SECTION_TITLE_KEY = {
    "executive_summary": "exec",
    "maturity_results": "results",
    "axis_findings": "axis_findings",
    "priorities": "priorities",
    "initiatives": "initiatives",
    "roadmap": "roadmap",
}



def _scale_key(ctx: dict, t: dict, locale: str) -> str:
    """FR-08 - the maturity criteria the scores were read against, printed once
    so a reader can interpret every axis score in the section that follows."""
    levels = ctx.get("levels") or {}
    if not levels:
        return ""
    rows = "".join(
        f'<tr><td class="mono num">{score}</td>'
        f'<td><b>{_esc(_pick(level, "label", locale))}</b></td>'
        f'<td>{_esc(_pick(level, "description", locale))}</td></tr>'
        for score, level in sorted(levels.items())
    )
    return (
        f'<div class="axis-block"><div class="axis-head">'
        f'<h4>{_esc(t["criteria"])}</h4></div>'
        f'<table class="data"><tbody>{rows}</tbody></table></div>'
    )


def _logo(brand: dict) -> str:
    """The template may carry a client logo as a data URI; otherwise the built-in
    maturity-ladder mark is drawn from the branding ramp."""
    logo = brand.get("logo_data_uri")
    if logo:
        return f'<img class="cover-logo" src="{_esc(logo)}" alt="">'
    ramp = brand.get("ramp") or RAMP
    bars = "".join(
        f'<i style="height:{h}%;background:{ramp[i]}"></i>'
        for i, h in enumerate((30, 47, 64, 82, 100))
    )
    return f'<div class="cover-mark">{bars}</div>'


def _comparison_block(ctx: dict, t: dict, axes: dict, locale: str) -> str:
    """Report section 9: comparison to prior assessments where available."""
    data = ctx.get("comparison")
    if not data:
        return ""
    delta = data.get("overall_delta")
    arrow = "" if delta is None else ("+" if delta > 0 else "")
    direction = ""
    if delta is not None and delta != 0:
        direction = t["improved"] if delta > 0 else t["declined"]

    rows = "".join(
        f'<tr><td class="mono dim">{_esc(r["code"])}</td>'
        f'<td class="mono num">{_num(r["previous"])}</td>'
        f'<td class="mono num">{_num(r["current"])}</td>'
        f'<td class="mono num" style="color:{"#1f6b4a" if r["delta"] > 0 else ("#9b3d2e" if r["delta"] < 0 else "inherit")}">'
        f'{"+" if r["delta"] > 0 else ""}{_num(r["delta"])}</td></tr>'
        for r in data.get("axes", [])
    )
    if not rows:
        return ""

    return f"""<h4 class="mt">{_esc(t['comparison'])}</h4>
<p class="dim" style="font-size:9pt">{_esc(data.get('previous_name') or '')} · {_esc((data.get('previous_submitted_at') or '')[:10])}
 &nbsp;·&nbsp; {_esc(t['overall'])}: {_num(data.get('previous_overall'))} → {_num(data.get('current_overall'))}
 {f'({arrow}{_num(delta)} {_esc(direction)})' if delta is not None else ''}</p>
<table class="data">
  <thead><tr><th>{_esc(t['axis'])}</th><th class="num">{_esc(t['previous'])}</th>
  <th class="num">{_esc(t['current'])}</th><th class="num">{_esc(t['change'])}</th></tr></thead>
  <tbody>{rows}</tbody>
</table>"""


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def _pick(row: Any, field: str, locale: str) -> str:
    value = getattr(row, f"{field}_{locale}", None) or getattr(
        row, f"{field}_{'en' if locale == 'ar' else 'ar'}", None
    )
    return str(value or "")


def _radar_svg(points: list[tuple[str, float]], size: int = 340, brand: dict | None = None) -> str:
    brand = brand or {}
    primary = brand.get("primary", "#1e3a5c")
    line = brand.get("line", "#c6d0da")
    surface = brand.get("surface_alt", "#f4f6f8")
    muted = brand.get("muted", "#6b7d8d")
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
        fill = surface if ring == 1.0 else "none"
        parts.append(f'<polygon points="{coords}" fill="{fill}" stroke="{line}" stroke-width="1"/>')
    for i in range(len(points)):
        x, y = at(i, 1)
        parts.append(f'<line x1="{cx}" y1="{cy}" x2="{x:.1f}" y2="{y:.1f}" stroke="{line}"/>')
    coords = " ".join(
        f"{x:.1f},{y:.1f}"
        for x, y in (at(i, max(0.0, (v - 1) / 4)) for i, (_, v) in enumerate(points))
    )
    parts.append(
        f'<polygon points="{coords}" fill="{primary}33" stroke="{primary}" stroke-width="2" stroke-linejoin="round"/>'
    )
    for i, (label, value) in enumerate(points):
        x, y = at(i, max(0.0, (value - 1) / 4))
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{primary}"/>')
        lx, ly = at(i, 1.16)
        parts.append(
            f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="8.5" fill="{muted}" '
            f'text-anchor="middle" dominant-baseline="middle">{_esc(label)}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)
def render_html(ctx: dict[str, Any]) -> str:
    locale = ctx["locale"]
    t = dict(ctx["t"])
    rtl = locale == "ar"
    result = ctx["result"]
    axes = ctx["axes"]
    levels = ctx["levels"]
    org = ctx["org"]
    brand = ctx["branding"]
    sections = ctx["sections"]
    copy_blocks = ctx.get("copy_blocks") or {}
    ramp = brand.get("ramp") or RAMP

    # FR-34: an administrator may retitle any section, and the branding block
    # supplies the confidentiality and footer wording.
    for key, item in sections.items():
        title = item.get(f"title_{locale}")
        if title and key in SECTION_TITLE_KEY:
            t[SECTION_TITLE_KEY[key]] = title
    t["confidential"] = brand.get(f"confidentiality_{locale}") or t["confidential"]
    t["prepared_by"] = brand.get(f"footer_{locale}") or t["prepared_by"]

    def on(key: str) -> bool:
        return sections.get(key, {}).get("enabled", True)

    def block(key: str) -> str:
        text = (copy_blocks.get(key) or {}).get(locale) if isinstance(copy_blocks.get(key), dict) else None
        return f'<p class="lede">{_esc(text)}</p>' if text else ""


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
<style>{render_stylesheet(rtl, brand)}</style></head><body>

<section class="cover">
  {_logo(brand)}
  <div class="eyebrow">{_esc(brand.get('organisation_name') or 'iValue Consult')}</div>
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

    if not on("cover"):
        out = [out[0].split('<section class="cover">')[0] + "</head><body>"]

    # ── executive summary ─────────────────────────────────────────────────
    narrative = ctx["narrative"]
    body = _pick(narrative, "body", locale) if narrative else ""
    if on("executive_summary"):
        out.append(f"""<section class="page">
<h2>{_esc(t['exec'])}</h2>
<div class="tiles">
  <div class="tile hero"><span class="tile-v">{_num(result['overall_score'])}</span><span class="tile-l">{_esc(t['overall'])}</span></div>
  <div class="tile"><span class="tile-v">{_esc(level_label(result['maturity_level']))}</span><span class="tile-l">{_esc(t['level'])}</span></div>
  <div class="tile"><span class="tile-v">{round(result['completeness']*100)}%</span><span class="tile-l">{_esc(t['completeness'])}</span></div>
  <div class="tile"><span class="tile-v">{round(result['evidence_completeness']*100)}%</span><span class="tile-l">{_esc(t['evidence'])}</span></div>
</div>
{f'<p class="lede">{_esc(body)}</p>' if body else ''}
{block('executive_summary')}
<div class="two-col">
  <div><h4>{_esc(t['strengths'])}</h4>{_chips(result['strengths'], axes, locale, 'ok')}</div>
  <div><h4>{_esc(t['gaps'])}</h4>{_chips(result['gaps'], axes, locale, 'bad')}</div>
</div>
{_comparison_block(ctx, t, axes, locale)}
<div class="note">{_esc(t['ai_note'])}</div>
</section>""")

    # ── maturity results ──────────────────────────────────────────────────
    rows = []
    for row in result["axes"]:
        pct = ((row["score"] - 1) / 4 * 100) if row["score"] is not None else 0
        colour = ramp[(row["maturity_level"] or 1) - 1] if row["maturity_level"] else brand['line']
        rows.append(f"""<tr>
  <td class="mono dim">{_esc(row['code'])}</td>
  <td>{_esc(axis_name(row['axis_id'], row['code']))}</td>
  <td class="bar-cell"><span class="bar"><i style="width:{pct:.0f}%;background:{colour}"></i></span></td>
  <td class="mono num">{_num(row['score']) if row['is_scored'] else _esc(t['not_scored'])}</td>
  <td class="mono num dim">{round(row['coverage']*100)}%</td>
</tr>""")

    heat = "".join(
        f'<div class="heat-cell" style="background:{ramp[(a["maturity_level"] or 1)-1] if a["maturity_level"] else brand["surface_alt"]};'
        f'color:{brand["ink"] if (a["maturity_level"] or 1) <= 2 else "#fff"}">'
        f'<span class="hc">{_esc(a["code"])}</span><span class="hv">{_num(a["score"]) if a["is_scored"] else "—"}</span></div>'
        for a in result["axes"]
    )

    if on("maturity_results"):
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
    {_radar_svg(radar, brand=brand)}
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

        colour = ramp[(row["maturity_level"] or 1) - 1] if row["maturity_level"] else brand['line']
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
    if on("axis_findings"):
        out.append(
            f'<section class="page"><h2>{_esc(t["axis_findings"])}</h2>'
            f'{block("axis_findings")}{"".join(blocks)}</section>'
        )

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
    if on("priorities"):
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
    initiatives = ctx["initiatives"] if on("initiatives") else []
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
            f'<section class="page"><h2>{_esc(t["initiatives"])}</h2>'
            f'{block("initiatives")}{cards}</section>'
        )
        if on("roadmap"):
            out.append(
                f'<section class="page"><h2>{_esc(t["roadmap"])}</h2>'
                f'{block("roadmap")}<div class="lanes">{"".join(lanes)}</div></section>'
            )
    elif on("initiatives"):
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
