"""Encryption at rest for customer evidence, and secret loading.

The security NFR lists "encryption in transit and at rest" and "secure secrets
management" as mandatory. Transit is TLS at the edge; this module covers the
other two.

Design notes
------------
* AES-256-GCM, one random 96-bit nonce per file, prepended to the ciphertext.
  GCM is authenticated, so a tampered evidence file fails to decrypt rather than
  silently returning altered bytes — which matters when the file is the proof
  behind a maturity score.
* The data key is derived per tenant from the master key with HKDF. One
  organisation's files therefore cannot be decrypted with another's derived key,
  so the tenant boundary survives even a raw filesystem or backup copy.
* Secrets are read from the environment, or from a file when the variable is
  suffixed `_FILE` — the convention Docker secrets and Kubernetes mounts use, so
  the master key never has to appear in a compose file or shell history.
"""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

NONCE_BYTES = 12
KEY_BYTES = 32
MAGIC = b"REMAS1"  # lets a reader tell an encrypted blob from a legacy plain file


def read_secret(name: str, default: str | None = None) -> str | None:
    """Environment variable, or the contents of the file named by `<NAME>_FILE`."""
    path = os.environ.get(f"{name}_FILE")
    if path:
        try:
            return Path(path).read_text(encoding="utf-8").strip()
        except OSError:
            return default
    return os.environ.get(name, default)


def _master_key(raw: str) -> bytes:
    """Accepts a base64 32-byte key, or any passphrase (hashed to 32 bytes)."""
    try:
        decoded = base64.urlsafe_b64decode(raw.encode())
        if len(decoded) == KEY_BYTES:
            return decoded
    except Exception:  # noqa: BLE001 - a passphrase is a legitimate input
        pass
    return hashlib.sha256(raw.encode("utf-8")).digest()


def derive_key(master: str, tenant_id: str) -> bytes:
    """Per-tenant data key. Distinct tenants never share key material."""
    return HKDF(
        algorithm=hashes.SHA256(),
        length=KEY_BYTES,
        salt=b"remas.evidence.v1",
        info=tenant_id.encode("utf-8"),
    ).derive(_master_key(master))


def encrypt(plaintext: bytes, master: str, tenant_id: str) -> bytes:
    nonce = os.urandom(NONCE_BYTES)
    ciphertext = AESGCM(derive_key(master, tenant_id)).encrypt(nonce, plaintext, MAGIC)
    return MAGIC + nonce + ciphertext


def decrypt(blob: bytes, master: str, tenant_id: str) -> bytes:
    if not is_encrypted(blob):
        # A file written before encryption was switched on stays readable.
        return blob
    nonce = blob[len(MAGIC) : len(MAGIC) + NONCE_BYTES]
    ciphertext = blob[len(MAGIC) + NONCE_BYTES :]
    return AESGCM(derive_key(master, tenant_id)).decrypt(nonce, ciphertext, MAGIC)


def is_encrypted(blob: bytes) -> bool:
    return blob[: len(MAGIC)] == MAGIC


def generate_master_key() -> str:
    """A fresh key, ready to paste into a secret store."""
    return base64.urlsafe_b64encode(os.urandom(KEY_BYTES)).decode()
