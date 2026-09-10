"""Bulk-loading iValue's master assessment content (FR-33).

Split deliberately in two halves:

* `parse` turns raw bytes into rows and touches no database. It is the half
  that carries all the awkward knowledge — Arabic and English column aliases,
  a criteria column that may hold both languages separated by `|`, truthiness
  in two languages — and it is now testable with a CSV string and no fixtures.
* `apply` writes those rows into a draft version.

The two used to be one 165-line `async def` inside the admin controller, which
meant every test of the column-alias logic needed an authenticated multipart
upload against a seeded database.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from typing import Any

from fastapi import status
from sqlalchemy.orm import Session

from app.core.errors import APIError
from app.models import Axis, FrameworkVersion, Question

#: Accepted column headings per field. The master sheet arrives in Arabic or
#: English depending on who produced it, so the importer matches both rather
#: than asking iValue to rewrite the file.
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "axis_code": ("axis_code", "axis", "pillar_code", "رمز المحور"),
    "axis_name_ar": ("axis_name_ar", "المحور", "اسم المحور"),
    "axis_name_en": ("axis_name_en", "axis_name", "pillar"),
    "axis_weight": ("axis_weight", "وزن المحور"),
    "question_code": ("question_code", "code", "رمز السؤال"),
    "text_ar": ("text_ar", "question_ar", "السؤال"),
    "text_en": ("text_en", "question_en", "question"),
    "guidance_ar": ("guidance_ar", "الإرشاد"),
    "guidance_en": ("guidance_en", "guidance"),
    "evidence_hint_ar": ("evidence_hint_ar", "الدليل", "المستند المطلوب"),
    "evidence_hint_en": ("evidence_hint_en", "evidence", "expected_document"),
    "weight": ("weight", "question_weight", "الوزن"),
    "is_mandatory": ("is_mandatory", "mandatory", "إلزامي"),
    "evidence_required": ("evidence_required", "requires_evidence", "دليل مطلوب"),
    # FR-08 — per-level maturity criteria, one column per level.
    "criteria_1": ("criteria_1", "level_1", "المستوى_1", "معيار_1"),
    "criteria_2": ("criteria_2", "level_2", "المستوى_2", "معيار_2"),
    "criteria_3": ("criteria_3", "level_3", "المستوى_3", "معيار_3"),
    "criteria_4": ("criteria_4", "level_4", "المستوى_4", "معيار_4"),
    "criteria_5": ("criteria_5", "level_5", "المستوى_5", "معيار_5"),
}

TRUTHY = ("1", "true", "yes", "y", "نعم", "إلزامي", "مطلوب")

#: Both languages in one cell, split by a pipe.
LANGUAGE_SEPARATOR = "|"

SPREADSHEET_SUFFIXES = (".xlsx", ".xlsm")
CSV_SUFFIX = ".csv"


@dataclass
class ImportResult:
    axes_created: int = 0
    questions_created: int = 0
    skipped: list[str] = field(default_factory=list)


def normalise_header(name: str) -> str | None:
    """Map one sheet heading onto a field name, or None if it is not ours."""
    key = (name or "").strip().lower().replace(" ", "_")
    for field_name, aliases in COLUMN_ALIASES.items():
        if key == field_name or key in aliases:
            return field_name
    return None


def truthy(value: Any) -> bool:
    return str(value).strip().lower() in TRUTHY


def parse_criteria(row: dict[str, Any]) -> dict[str, dict[str, str]] | None:
    """The 1-5 wording for one question (FR-08).

    A cell may carry both languages split by `|`; when it does not, the same
    text serves both rather than leaving one language blank in the report.
    """
    criteria: dict[str, dict[str, str]] = {}
    for level in range(1, 6):
        value = row.get(f"criteria_{level}")
        if not value:
            continue
        text = str(value).strip()
        if LANGUAGE_SEPARATOR in text:
            ar, en = (part.strip() for part in text.split(LANGUAGE_SEPARATOR, 1))
        else:
            ar = en = text
        criteria[str(level)] = {"ar": ar, "en": en}
    return criteria or None


def parse(raw: bytes, filename: str) -> list[dict[str, Any]]:
    """Rows from a master Excel sheet or an equivalent CSV. No database access."""
    name = (filename or "").lower()
    if name.endswith(SPREADSHEET_SUFFIXES):
        rows = _parse_spreadsheet(raw)
    elif name.endswith(CSV_SUFFIX):
        rows = _parse_csv(raw)
    else:
        raise APIError("import.unsupported_format", status.HTTP_415_UNSUPPORTED_MEDIA_TYPE)

    if not rows:
        raise APIError("import.empty_file", status.HTTP_422_UNPROCESSABLE_CONTENT)
    return rows


def _parse_spreadsheet(raw: bytes) -> list[dict[str, Any]]:
    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    try:
        sheet = workbook.worksheets[0]
        iterator = sheet.iter_rows(values_only=True)
        try:
            header = next(iterator)
        except StopIteration:
            raise APIError(
                "import.empty_file", status.HTTP_422_UNPROCESSABLE_CONTENT
            ) from None
        mapping = {i: normalise_header(str(h or "")) for i, h in enumerate(header)}
        rows = []
        for values in iterator:
            row = {
                mapping[i]: values[i]
                for i in range(len(values))
                if i in mapping and mapping[i] and values[i] not in (None, "")
            }
            if row:
                rows.append(row)
        return rows
    finally:
        workbook.close()


def _parse_csv(raw: bytes) -> list[dict[str, Any]]:
    # utf-8-sig: Excel writes a BOM, and it would otherwise corrupt the first
    # column heading and silently drop that column from the import.
    text = raw.decode("utf-8-sig", errors="replace")
    rows = []
    for record in csv.DictReader(io.StringIO(text)):
        row = {}
        for key, value in record.items():
            field_name = normalise_header(key or "")
            if field_name and value not in (None, ""):
                row[field_name] = value
        if row:
            rows.append(row)
    return rows


def apply(
    db: Session,
    version: FrameworkVersion,
    rows: list[dict[str, Any]],
    *,
    replace: bool = True,
) -> ImportResult:
    """Write parsed rows into a draft version.

    A row that cannot be used is skipped with a reason rather than aborting the
    whole import — a 160-row master sheet with one bad line should load the
    other 159 and say what it dropped.
    """
    result = ImportResult()

    if replace:
        for axis in list(version.axes):
            db.delete(axis)
        db.flush()

    axes_by_code: dict[str, Axis] = {a.code: a for a in version.axes}

    # `start=2` so the reported row number matches what the administrator sees
    # in the spreadsheet, where row 1 is the header.
    for index, row in enumerate(rows, start=2):
        axis_code = str(row.get("axis_code") or "").strip()
        if not axis_code:
            result.skipped.append(f"row {index}: missing axis_code")
            continue

        axis = axes_by_code.get(axis_code)
        if axis is None:
            axis = Axis(
                framework_version_id=version.id,
                code=axis_code,
                order_index=len(axes_by_code) + 1,
                name_ar=str(row.get("axis_name_ar") or axis_code),
                name_en=str(row.get("axis_name_en") or axis_code),
                weight=float(row.get("axis_weight") or 1.0),
            )
            db.add(axis)
            db.flush()
            axes_by_code[axis_code] = axis
            result.axes_created += 1

        question_code = str(row.get("question_code") or "").strip()
        text_ar = str(row.get("text_ar") or "").strip()
        text_en = str(row.get("text_en") or "").strip()
        if not question_code or not (text_ar or text_en):
            result.skipped.append(f"row {index}: missing question code or text")
            continue

        db.add(
            Question(
                axis_id=axis.id,
                code=question_code,
                order_index=len(axis.questions) + result.questions_created + 1,
                text_ar=text_ar or text_en,
                text_en=text_en or text_ar,
                guidance_ar=row.get("guidance_ar"),
                guidance_en=row.get("guidance_en"),
                evidence_hint_ar=row.get("evidence_hint_ar"),
                evidence_hint_en=row.get("evidence_hint_en"),
                weight=float(row.get("weight") or 1.0),
                is_mandatory=truthy(row.get("is_mandatory", True)),
                evidence_required=truthy(row.get("evidence_required", False)),
                criteria=parse_criteria(row),
            )
        )
        result.questions_created += 1

    return result


def template_csv() -> str:
    """The exact column set the importer expects, with one worked example."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(list(COLUMN_ALIASES))
    writer.writerow(
        [
            "AX01", "الحوكمة المؤسسية", "Corporate Governance", "1.2", "AX01-Q1",
            "هل يوجد ميثاق حوكمة معتمد؟", "Is there an approved governance charter?",
            "", "", "ميثاق الحوكمة", "Governance charter", "1.5", "yes", "yes",
            "لا يوجد | None", "متفرّق | Scattered", "جزئي | Partial",
            "منهجي | Systematic", "متكامل | Integrated",
        ]
    )
    return buffer.getvalue()
