"""Final report generation — BRD section 9.

Three modules behind one public surface, split along the dependencies each part
actually has:

    renderer.py   pure HTML from a context dict — no database, no framework
    context.py    gathers that context from the database
    pdf.py        prints the HTML through headless Chromium
    export.py     the structured JSON export

All seven required sections are produced: cover, executive summary, maturity
results, axis-level findings, priority improvement areas, recommended
initiatives and the implementation roadmap.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Assessment
from app.services.reporting.context import build_context, resolve_template
from app.services.reporting.export import structured_export
from app.services.reporting.pdf import render_pdf
from app.services.reporting.renderer import render_html


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


__all__ = [
    "build_context",
    "generate",
    "render_html",
    "render_pdf",
    "report_path",
    "resolve_template",
    "structured_export",
]
