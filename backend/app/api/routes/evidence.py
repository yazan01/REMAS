from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, get_assessment, get_current_user, require_ivalue
from app.core.config import settings
from app.core.errors import APIError
from app.core.security import utcnow
from app.db.session import get_db
from app.models import Assessment, Document, DocumentLink, EvidenceStatus, User
from app.models.enums import IVALUE_ROLES
from app.schemas import DocumentOut, EvidenceLinkIn, EvidenceLinkOut, EvidenceStatusIn
from app.services import audit, evidence_store

router = APIRouter(tags=["evidence"])

# Rendered inline in the browser; anything else is downloaded (FR-16 preview).
PREVIEWABLE = {"application/pdf", "image/png", "image/jpeg"}


def _load_document(db: Session, document_id: str, user: User) -> Document:
    document = db.get(Document, document_id)
    if document is None or document.deleted_at is not None:
        raise APIError("document.not_found", status.HTTP_404_NOT_FOUND)
    if document.organization_id != user.organization_id and user.role not in IVALUE_ROLES:
        raise APIError("document.not_found", status.HTTP_404_NOT_FOUND)
    return document


@router.get("/documents", response_model=list[DocumentOut])
def list_documents(
    category: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Document]:
    stmt = (
        select(Document)
        .where(Document.organization_id == user.organization_id, Document.deleted_at.is_(None))
        .order_by(Document.created_at.desc())
    )
    if category:
        stmt = stmt.where(Document.category == category)
    return list(db.scalars(stmt))


@router.get("/documents/categories", response_model=list[str])
def list_categories(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[str]:
    rows = db.scalars(
        select(Document.category)
        .where(
            Document.organization_id == user.organization_id,
            Document.deleted_at.is_(None),
            Document.category.isnot(None),
        )
        .distinct()
    )
    return sorted({c for c in rows if c})


@router.post("/documents", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    category: str | None = Form(default=None),
    description: str | None = Form(default=None),
    supersedes_id: str | None = Form(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Document:
    """One upload, reusable across questions (BRD FR-14 / FR-16).

    Passing `supersedes_id` replaces a specific document explicitly (FR-19);
    otherwise a same-named upload is treated as the next version of it.
    """
    content = await file.read()
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise APIError("document.too_large", status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
    if file.content_type not in settings.allowed_upload_types:
        raise APIError("document.unsupported_type", status.HTTP_415_UNSUPPORTED_MEDIA_TYPE)

    digest = evidence_store.digest(content)
    suffix = Path(file.filename or "").suffix[:10]
    # The stored name is the digest, so identical bytes are not stored twice —
    # but encryption uses a fresh nonce, so each write is still distinct on disk.
    target = evidence_store.path_for(user.organization_id, content, suffix)
    evidence_store.write(target, content, user.organization_id)

    previous: Document | None = None
    if supersedes_id:
        previous = _load_document(db, supersedes_id, user)
    else:
        previous = db.scalars(
            select(Document)
            .where(
                Document.organization_id == user.organization_id,
                Document.filename == (file.filename or "document"),
                Document.deleted_at.is_(None),
            )
            .order_by(Document.version.desc())
        ).first()

    document = Document(
        organization_id=user.organization_id,
        filename=file.filename or "document",
        stored_path=str(target),
        content_type=file.content_type,
        size_bytes=len(content),
        sha256=digest,
        version=(previous.version + 1) if previous else 1,
        supersedes_id=previous.id if previous else None,
        category=category,
        description=description,
        uploaded_by_id=user.id,
    )
    db.add(document)
    db.flush()

    if supersedes_id and previous is not None:
        # An explicit replacement carries the old document's links forward, so
        # the reviewer does not have to re-attach every question by hand.
        for link in db.scalars(
            select(DocumentLink).where(DocumentLink.document_id == previous.id)
        ):
            link.document_id = document.id
            link.status = EvidenceStatus.UPLOADED
        previous.deleted_at = utcnow()

    audit.record(
        db,
        action="evidence.replaced" if supersedes_id else "evidence.uploaded",
        entity_type="document",
        entity_id=document.id,
        actor=user,
        payload={
            "filename": document.filename,
            "size": document.size_bytes,
            "encrypted": settings.encrypt_evidence,
            "supersedes": supersedes_id,
            "category": category,
        },
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(document)
    return document


def _serve(document: Document, disposition: str) -> Response:
    """Hand a stored evidence file back to the browser.

    The headers are the point. These bytes came from a customer upload, and the
    content type beside them is whatever that customer's browser declared at
    upload time — it is metadata, not a fact about the file. So a document can
    always be bytes of one kind wearing the label of another.

    `nosniff` is what makes that harmless: without it a browser is free to
    disregard the declared type, sniff the content, and decide a file labelled
    image/png is really HTML — which it would then execute on this API's own
    origin, with the reviewer's session attached. With it, the declared type is
    the only type, and mislabelled bytes render as broken rather than as script.

    The `preview` route is the one that needs this, because it serves inline;
    `download` sends the same header anyway rather than making the safety of a
    response depend on which handler happened to build it.
    """
    return Response(
        content=evidence_store.read(document),
        media_type=document.content_type,
        headers={
            "Content-Disposition": f'{disposition}; filename="{document.filename}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/documents/{document_id}/download")
def download_document(
    document_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Response:
    document = _load_document(db, document_id, user)
    if not evidence_store.exists(document):
        raise APIError("document.not_found", status.HTTP_404_NOT_FOUND)
    return _serve(document, "attachment")


@router.get("/documents/{document_id}/preview")
def preview_document(
    document_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Response:
    """FR-16 preview — the same bytes served inline instead of as an attachment,
    so a reviewer can read a PDF without leaving the page."""
    document = _load_document(db, document_id, user)
    if document.content_type not in PREVIEWABLE:
        raise APIError("document.not_previewable", status.HTTP_415_UNSUPPORTED_MEDIA_TYPE)
    if not evidence_store.exists(document):
        raise APIError("document.not_found", status.HTTP_404_NOT_FOUND)
    return _serve(document, "inline")


@router.patch("/documents/{document_id}", response_model=DocumentOut)
def update_document(
    document_id: str,
    payload: dict,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Document:
    """Document metadata — categorisation and description (FR-16)."""
    document = _load_document(db, document_id, user)
    for field in ("category", "description"):
        if field in payload:
            setattr(document, field, payload[field])
    audit.record(
        db,
        action="evidence.metadata_updated",
        entity_type="document",
        entity_id=document.id,
        actor=user,
        payload={"fields": sorted(payload)},
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(document)
    return document


@router.get("/documents/{document_id}/history", response_model=list[dict])
def document_history(
    document_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[dict]:
    """FR-19 — the version chain behind a piece of evidence."""
    document = _load_document(db, document_id, user)
    chain: list[dict] = []
    cursor: Document | None = document
    seen: set[str] = set()
    while cursor is not None and cursor.id not in seen:
        seen.add(cursor.id)
        chain.append(
            {
                "id": cursor.id,
                "filename": cursor.filename,
                "version": cursor.version,
                "size_bytes": cursor.size_bytes,
                "created_at": cursor.created_at.isoformat(),
                "superseded": cursor.deleted_at is not None,
            }
        )
        cursor = db.get(Document, cursor.supersedes_id) if cursor.supersedes_id else None
    return chain


@router.delete(
    "/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
def delete_document(
    document_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    document = db.get(Document, document_id)
    if document is None or document.organization_id != user.organization_id:
        raise APIError("document.not_found", status.HTTP_404_NOT_FOUND)

    # Soft delete: the audit history of an evidence action must survive (FR-19).
    document.deleted_at = utcnow()
    audit.record(
        db,
        action="evidence.deleted",
        entity_type="document",
        entity_id=document.id,
        actor=user,
        ip_address=client_ip(request),
    )
    db.commit()


@router.get("/assessments/{assessment_id}/evidence", response_model=list[EvidenceLinkOut])
def list_links(
    assessment: Assessment = Depends(get_assessment), db: Session = Depends(get_db)
) -> list[EvidenceLinkOut]:
    links = db.scalars(
        select(DocumentLink).where(DocumentLink.assessment_id == assessment.id)
    )
    out: list[EvidenceLinkOut] = []
    for link in links:
        out.append(
            EvidenceLinkOut(
                id=link.id,
                document_id=link.document_id,
                question_id=link.question_id,
                status=link.status,
                reviewer_note=link.reviewer_note,
                filename=link.document.filename if link.document else None,
                created_at=link.created_at,
            )
        )
    return out


@router.post(
    "/assessments/{assessment_id}/evidence",
    response_model=list[EvidenceLinkOut],
    status_code=status.HTTP_201_CREATED,
)
def link_evidence(
    payload: EvidenceLinkIn,
    request: Request,
    assessment: Assessment = Depends(get_assessment),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[EvidenceLinkOut]:
    document = db.get(Document, payload.document_id)
    if document is None or document.organization_id != assessment.organization_id:
        raise APIError("document.not_found", status.HTTP_404_NOT_FOUND)

    from app.services.assessment_service import selected_axes

    allowed = {q.id for axis in selected_axes(db, assessment) for q in axis.questions}
    existing = {
        (link.question_id, link.document_id)
        for link in db.scalars(
            select(DocumentLink).where(DocumentLink.assessment_id == assessment.id)
        )
    }

    created: list[DocumentLink] = []
    for question_id in payload.question_ids:
        if question_id not in allowed:
            raise APIError("question.not_in_assessment", status.HTTP_400_BAD_REQUEST)
        if (question_id, document.id) in existing:
            continue
        link = DocumentLink(
            document_id=document.id,
            assessment_id=assessment.id,
            question_id=question_id,
            status=EvidenceStatus.UPLOADED,
            linked_by_id=user.id,
        )
        db.add(link)
        created.append(link)

    audit.record(
        db,
        action="evidence.linked",
        entity_type="assessment",
        entity_id=assessment.id,
        actor=user,
        payload={"document_id": document.id, "question_ids": payload.question_ids},
        ip_address=client_ip(request),
    )
    db.commit()
    return [
        EvidenceLinkOut(
            id=link.id,
            document_id=link.document_id,
            question_id=link.question_id,
            status=link.status,
            reviewer_note=link.reviewer_note,
            filename=document.filename,
            created_at=link.created_at,
        )
        for link in created
    ]


@router.patch("/evidence/{link_id}/status", response_model=EvidenceLinkOut)
def set_link_status(
    link_id: str,
    payload: EvidenceStatusIn,
    request: Request,
    user: User = Depends(require_ivalue),
    db: Session = Depends(get_db),
) -> EvidenceLinkOut:
    """Reviewer decision on a piece of evidence (BRD FR-18)."""
    link = db.get(DocumentLink, link_id)
    if link is None:
        raise APIError("document.not_found", status.HTTP_404_NOT_FOUND)
    previous = link.status
    link.status = payload.status
    link.reviewer_note = payload.reviewer_note
    audit.record(
        db,
        action="evidence.status_changed",
        entity_type="document_link",
        entity_id=link.id,
        actor=user,
        payload={"from": previous, "to": str(payload.status)},
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(link)
    return EvidenceLinkOut(
        id=link.id,
        document_id=link.document_id,
        question_id=link.question_id,
        status=link.status,
        reviewer_note=link.reviewer_note,
        filename=link.document.filename if link.document else None,
        created_at=link.created_at,
    )


@router.delete(
    "/evidence/{link_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
def unlink_evidence(
    link_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    link = db.get(DocumentLink, link_id)
    if link is None:
        raise APIError("document.not_found", status.HTTP_404_NOT_FOUND)
    assessment = db.get(Assessment, link.assessment_id)
    if assessment is None or (
        assessment.organization_id != user.organization_id and user.role not in IVALUE_ROLES
    ):
        raise APIError("document.not_found", status.HTTP_404_NOT_FOUND)
    audit.record(
        db,
        action="evidence.unlinked",
        entity_type="document_link",
        entity_id=link.id,
        actor=user,
        payload={"question_id": link.question_id, "document_id": link.document_id},
        ip_address=client_ip(request),
    )
    db.delete(link)
    db.commit()
