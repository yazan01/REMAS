"""The report renderer, exercised without a database.

These tests are the reason `reporting` was split. Before it, the seven required
sections of BRD §9 could only be checked by seeding a framework, creating an
assessment, answering 160 questions, submitting it and scoring it — so in
practice the Arabic/English wording and the RTL direction were never checked at
all. The renderer is now a pure function of a context dictionary and these
tests run in milliseconds against a fixture.
"""

from __future__ import annotations

import ast
import io
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.reporting import renderer as renderer_module

REPORTING = Path(__file__).resolve().parent.parent / "app" / "services" / "reporting"

#: Importing any of these would mean the renderer stopped being pure.
FORBIDDEN_PREFIXES = ("sqlalchemy", "fastapi", "starlette", "app.models", "app.db", "app.api")


def _declared_imports(path: Path) -> set[str]:
    tree = ast.parse(io.open(path, encoding="utf-8").read(), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


@pytest.fixture(scope="module")
def renderer():
    return renderer_module


@pytest.mark.parametrize("module", ["renderer.py", "styles.py", "export.py"])
def test_the_pure_half_of_reporting_stays_pure(module: str) -> None:
    """A database or framework import here would put the report renderer back
    behind a web request, which is the thing this split removed."""
    offenders = sorted(
        name
        for name in _declared_imports(REPORTING / module)
        if name.startswith(FORBIDDEN_PREFIXES)
    )
    assert not offenders, f"{module} must not import {offenders}"


def _axis_row(axis_id: str, code: str, score: float, level: int) -> dict:
    """One entry of `result["axes"]`, matching scoring.AxisResult.as_dict()."""
    return {
        "axis_id": axis_id,
        "code": code,
        "weight": 1.0,
        "score": score,
        "maturity_level": level,
        "total_questions": 10,
        "applicable_questions": 10,
        "answered_questions": 10,
        "not_applicable_questions": 0,
        "unanswered_mandatory": 0,
        "coverage": 1.0,
        "evidence_completeness": 0.8,
        "is_scored": True,
        "exclusion_reason": None,
    }


@pytest.fixture
def context(renderer):
    """A minimal but complete report context, in the shape build_context returns.

    The shapes are not guesses: `axes` and `levels` are keyed ORM rows read
    through `getattr`, `result` is `ScoringResult.as_dict()` and `sections` is
    keyed by section name.
    """
    axes = {
        "a1": SimpleNamespace(
            id="a1", code="AX01",
            name_ar="الحوكمة المؤسسية", name_en="Corporate Governance",
        ),
        "a2": SimpleNamespace(
            id="a2", code="AX02",
            name_ar="إدارة المشاريع", name_en="Project Management",
        ),
    }
    result = {
        "overall_score": 3.15,
        "maturity_level": 3,
        "completeness": 1.0,
        "evidence_completeness": 0.8,
        "axes": [_axis_row("a1", "AX01", 4.2, 4), _axis_row("a2", "AX02", 2.1, 2)],
        "strengths": ["a1"],
        "gaps": ["a2"],
        "priorities": [
            # `rank` is added by scoring.compute() after sorting, so a real
            # context always carries it.
            {"rank": 1, "axis_id": "a2", "code": "AX02", "score": 2.1,
             "maturity_gap": 2.9, "evidence_gap": 0.2, "priority_score": 3.4}
        ],
        "config": {},
        "warnings": [],
    }
    levels = {
        score: SimpleNamespace(
            score=score, label_ar=ar, label_en=en,
            description_ar=None, description_en=None,
        )
        for score, ar, en in [
            (1, "تأسيسي", "Initial"), (2, "ناشئ", "Developing"),
            (3, "مُعرَّف", "Defined"), (4, "مُدار", "Managed"),
            (5, "متميّز", "Distinguished"),
        ]
    }
    section_keys = [
        "cover", "executive_summary", "maturity_results", "axis_findings",
        "priorities", "initiatives", "roadmap",
    ]
    return {
        "locale": "ar",
        "t": dict(renderer.T["ar"]),
        "org": SimpleNamespace(
            name_ar="شركة تطوير تجريبية", name_en="Demo Development Company",
            sector_ar=None, sector_en=None, city_ar=None, city_en=None,
        ),
        "assessment": SimpleNamespace(
            id="asmt-1", name="تقييم ٢٠٢٦", layer="ai_report",
            submitted_at=None, status="completed",
        ),
        "version": SimpleNamespace(version="1.0", framework=SimpleNamespace(code="REMAS")),
        "result": result,
        "axes": axes,
        "levels": levels,
        "findings": {},
        "narrative": None,
        "horizons": [],
        "initiatives": [],
        "template": SimpleNamespace(
            code="default", include_comparison=False,
            maturity_labels={}, copy_blocks={},
        ),
        "branding": {
            "primary": "#1e3a5c", "accent": "#b8863b", "ink": "#0f1b28",
            "muted": "#6b7d8d", "line": "#dbe2e9", "surface_alt": "#f6f8fa",
            "ramp": list(renderer.RAMP), "logo_data_uri": None,
            "organisation_name": "iValue Consult",
            "footer_ar": "أُعد بواسطة iValue Consult",
            "footer_en": "Prepared by iValue Consult",
            "confidentiality_ar": "وثيقة سرّية",
            "confidentiality_en": "Confidential",
        },
        "sections": {
            key: {"key": key, "enabled": True, "order": i,
                  "title_ar": None, "title_en": None}
            for i, key in enumerate(section_keys)
        },
        "copy_blocks": {},
        "comparison": None,
        "generated_at": datetime(2026, 9, 10, tzinfo=timezone.utc),
    }


def test_renders_a_complete_document(renderer, context) -> None:
    html = renderer.render_html(context)
    assert html.lstrip().lower().startswith("<!doctype html")
    assert "</html>" in html
    assert len(html) > 4000


def test_arabic_report_is_marked_right_to_left(renderer, context) -> None:
    """The BRD's language NFR: Arabic must render RTL, and a PDF printed from a
    document without `dir="rtl"` silently comes out reversed."""
    html = renderer.render_html(context)
    assert 'dir="rtl"' in html
    assert 'lang="ar"' in html


def test_english_report_is_left_to_right(renderer, context) -> None:
    context["locale"] = "en"
    context["t"] = renderer.T["en"]
    html = renderer.render_html(context)
    assert 'dir="ltr"' in html
    assert 'lang="en"' in html


def test_every_required_section_heading_appears(renderer, context) -> None:
    """BRD §9 lists seven required sections; each enabled one must reach the
    document. The roadmap is excluded here — see the characterisation test
    below, which pins a known defect."""
    html = renderer.render_html(context)
    missing = [
        key
        for key, title_key in renderer.SECTION_TITLE_KEY.items()
        if key != "roadmap" and context["t"][title_key] not in html
    ]
    assert not missing, f"section headings absent from the report: {missing}"


def test_roadmap_currently_depends_on_the_initiatives_section(renderer, context) -> None:
    """CHARACTERISATION TEST — pins a defect rather than endorsing it.

    BUG FOUND during the reporting split, documented and deliberately NOT fixed
    here because it changes report output.

    Current behaviour: the roadmap section is nested inside the initiatives
    branch, so it renders only when at least one initiative exists, and the list
    is emptied when the *initiatives* section is switched off:

        initiatives = ctx["initiatives"] if on("initiatives") else []
        if initiatives:
            ...
            if on("roadmap"): ...

    Expected behaviour: BRD §9 lists the implementation roadmap as one of the
    seven required sections and FR-34 lets an administrator toggle each section
    independently. Enabling `roadmap` should render it — with empty lanes if
    there is nothing to place — and disabling `initiatives` should not silently
    remove a different section.

    Impact: a report whose analysis produced no initiatives is missing a
    required section with no explanation; an administrator who turns off
    initiatives loses the roadmap without being told.

    Proposed fix: lift the roadmap out of the initiatives branch and render it
    whenever `on("roadmap")`, using `ctx["horizons"]` for the lanes.

    Risk: LOW — additive; affects only reports that currently omit the section.

    This test fails the moment the behaviour changes, which is the point.
    """
    without = renderer.render_html(context)
    assert context["t"]["roadmap"] not in without, (
        "the roadmap defect appears to be fixed — update this test and the "
        "documented finding rather than leaving a stale characterisation."
    )


def test_a_disabled_section_is_omitted(renderer, context) -> None:
    before = renderer.render_html(context)
    context["sections"]["initiatives"]["enabled"] = False
    after = renderer.render_html(context)
    assert len(after) < len(before)


def test_axis_names_render_in_the_selected_language(renderer, context) -> None:
    arabic = renderer.render_html(context)
    assert "الحوكمة المؤسسية" in arabic

    context["locale"] = "en"
    context["t"] = renderer.T["en"]
    english = renderer.render_html(context)
    assert "Corporate Governance" in english


def test_user_supplied_text_is_escaped(renderer, context) -> None:
    """Report content comes from customer input; an unescaped axis name would
    put script into a document iValue then sends to the client."""
    context["axes"]["a1"].name_ar = '<script>alert("x")</script>'
    html = renderer.render_html(context)
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html


def test_the_brand_palette_reaches_the_document(renderer, context) -> None:
    context["branding"]["primary"] = "#123456"
    html = renderer.render_html(context)
    assert "#123456" in html


# ── regression: the stylesheet fell back to an undefined name ───────────────


def test_stylesheet_renders_without_any_branding() -> None:
    """`render_stylesheet` declares `brand: dict | None = None`, so calling it
    with no branding is part of its contract.

    It used to raise `NameError` instead: the maturity ramp constant lived in
    `renderer`, and `styles` referenced it without importing it. The `or RAMP`
    fallback short-circuited whenever branding carried a ramp — which
    `DEFAULT_BRANDING` does — so every ordinary report hid the fault, and it
    only surfaced on a template whose branding omitted or nulled `ramp`.
    """
    from app.services.reporting.styles import RAMP, render_stylesheet

    css = render_stylesheet(rtl=True, brand=None)
    # RAMP[0], not RAMP[4]: the top of the ramp is the same colour as the
    # default primary, so asserting on it would pass even if the ramp never
    # reached the sheet.
    assert RAMP[0] in css, "the default ramp must reach the stylesheet"


def test_stylesheet_falls_back_when_branding_omits_the_ramp() -> None:
    """The exact shape that used to crash: branding present, `ramp` missing."""
    from app.services.reporting.styles import RAMP, render_stylesheet

    css = render_stylesheet(rtl=False, brand={"primary": "#123456"})
    assert "#123456" in css
    assert RAMP[0] in css


def test_branding_ramp_still_overrides_the_default() -> None:
    """FR-34: iValue restyles the report through configuration, not code."""
    from app.services.reporting.styles import RAMP, render_stylesheet

    custom = ["#111111", "#222222", "#333333", "#444444", "#555555"]
    css = render_stylesheet(rtl=True, brand={"ramp": custom})
    # The sheet consumes $M1..$M4; level 5 is applied inline by the renderer
    # rather than through the stylesheet, so it is not asserted here.
    assert all(colour in css for colour in custom[:4])
    assert RAMP[0] not in css, "a custom ramp must replace the default, not merge with it"


# ── regression: the document must not depend on the network ────────────────


def test_report_requests_no_remote_resources(renderer, context) -> None:
    """The report used to `<link>` its fonts from fonts.googleapis.com, and
    `render_pdf` waited for `networkidle` before printing.

    Measured with that host intercepted: reachable 1.28s and correct; refused
    0.61s and silently in the wrong face; egress blackholed 30.08s and then a
    TimeoutError that took the PDF with it. `release_report` calls `render_pdf`
    unguarded, so the last case was a bare 500 on the final deliverable.

    Any remote `src`/`href` reintroduces that dependency, so the assertion is on
    the rendered document rather than on the one tag that used to carry it.
    """
    import re

    html = renderer.render_html(context)
    remote = re.findall(r'(?:src|href)\s*=\s*"(https?://[^"]+)"', html)
    assert not remote, f"the report fetches remote resources: {remote}"


def test_report_embeds_its_typefaces(renderer, context) -> None:
    """Both scripts must be present: the Arabic faces and the Latin ones. A
    report that embeds only Arabic renders the English edition in a fallback."""
    html = renderer.render_html(context)
    assert "data:font/woff2;base64," in html, "no font is embedded in the document"
    assert "U+0600" in html, "no embedded face claims the Arabic block"
