"""Tenant-scoped storage for evidence files, encrypted at rest.

This module owns two things and nothing else: where a tenant's files live on
disk, and the AES-256-GCM envelope around them. Everything above it — the
upload handler, the download handler, the AI extraction stage — asks this
module for bytes and never touches `Path` or `crypto` directly.

Why it exists as its own module: the reading half used to live inside the
evidence *route*, so the AI pipeline had to import an HTTP controller to open a
file. That made the analysis engine unusable outside a web request and inverted
the dependency direction (application -> presentation). The rule now runs the
right way round: the route and the pipeline both depend on this service.

Encryption is deliberately tolerant on the way out. A deployment that switches
`ENCRYPT_EVIDENCE` on mid-life still has plaintext files on disk from before;
`read` detects the envelope rather than assuming it, so old documents stay
readable (BRD backward-compatibility, and the reason `is_encrypted` exists).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from cryptography.exceptions import InvalidTag

from app.core import crypto
from app.core.config import settings
from app.models import Document


class UndecryptableEvidence(RuntimeError):
    """The stored bytes will not open with the key this process is holding.

    Almost always a key-lifecycle event rather than a corrupt file: the master
    key was rotated, a backup was restored under a different one, or — in
    development — the process generated a fresh ephemeral key at start-up and
    the file was written by a previous run.

    It is a distinct type because the caller must be able to tell it apart from
    a missing file: the file is there, the ciphertext is intact, and no amount
    of retrying will help.
    """


def tenant_dir(organization_id: str) -> Path:
    """One directory per organisation — the filesystem mirrors the tenancy
    boundary, so a path can never be built that spans two tenants."""
    path = settings.storage_dir / organization_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def digest(content: bytes) -> str:
    """Content hash, used as the stored filename.

    Deriving the name from the bytes rather than from the uploaded filename is
    what makes path traversal structurally impossible: a caller cannot smuggle
    `../` through a SHA-256 hex digest.
    """
    return hashlib.sha256(content).hexdigest()


def path_for(organization_id: str, content: bytes, suffix: str) -> Path:
    return tenant_dir(organization_id) / f"{digest(content)}{suffix}"


def write(path: Path, content: bytes, organization_id: str) -> None:
    """Seal with a key derived for this tenant alone, then persist."""
    if settings.encrypt_evidence and settings.evidence_master_key:
        content = crypto.encrypt(content, settings.evidence_master_key, organization_id)
    path.write_bytes(content)


def read(document: Document) -> bytes:
    """Plaintext bytes for a stored document, whatever state it was written in.

    A wrong key raises `UndecryptableEvidence` rather than letting the
    cryptography layer's `InvalidTag` escape: that exception carries no context
    about which document failed or why, and reaching the HTTP layer unhandled it
    becomes a bare 500 with a plain-text body the client cannot render.
    """
    blob = Path(document.stored_path).read_bytes()
    if settings.evidence_master_key and crypto.is_encrypted(blob):
        try:
            return crypto.decrypt(
                blob, settings.evidence_master_key, document.organization_id
            )
        except InvalidTag as exc:
            raise UndecryptableEvidence(document.id) from exc
    return blob


def exists(document: Document) -> bool:
    return Path(document.stored_path).exists()
