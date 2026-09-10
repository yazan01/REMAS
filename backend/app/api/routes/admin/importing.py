"""Bulk content import from iValue's master sheet (FR-33).

Thin by design: this module reads the upload, hands the bytes to
`services/content_import.py`, records the audit entry and returns the counts.
The column aliases, the two-language criteria cells and the truthiness rules
live in the service, where they can be tested without an HTTP request.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import client_ip, require_ivalue
from app.db.session import get_db
from app.models import User
from app.services import audit, content_import, framework_service

router = APIRouter()


@router.post("/versions/{version_id}/import", response_model=dict)
async def import_content(
    version_id: str,
    request: Request,
    file: UploadFile = File(...),
    replace: bool = Query(default=True),
    user: User = Depends(require_ivalue),
    db: Session = Depends(get_db),
) -> dict:
    """Bulk-load iValue's master assessment content (FR-33).

    Accepts the master Excel file or a CSV with the same columns. Column names
    are matched in Arabic or English, so the sheet does not have to be rewritten
    to import it.
    """
    version = framework_service.assert_editable(
        framework_service.load_version(db, version_id)
    )
    rows = content_import.parse(await file.read(), file.filename or "")
    result = content_import.apply(db, version, rows, replace=replace)

    audit.record(
        db, action="admin.content_imported", entity_type="framework_version",
        entity_id=version.id, actor=user,
        payload={"file": file.filename, "axes": result.axes_created,
                 "questions": result.questions_created, "skipped": len(result.skipped)},
        ip_address=client_ip(request),
    )
    db.commit()
    return {
        "version_id": version.id,
        "axes_created": result.axes_created,
        "questions_created": result.questions_created,
        "skipped": result.skipped[:25],
        "skipped_count": len(result.skipped),
    }


@router.get("/import-template.csv", response_class=StreamingResponse)
def import_template(_u: User = Depends(require_ivalue)) -> StreamingResponse:
    """The exact column set the importer expects."""
    return StreamingResponse(
        iter([content_import.template_csv()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="remas-import-template.csv"'},
    )
