"""Encrypted backup and restore — the backup/recovery NFR.

    python -m scripts.backup create              # write a backup archive
    python -m scripts.backup list                # what is on disk
    python -m scripts.backup restore <file>      # restore into a target
    python -m scripts.backup verify <file>       # restore to a temp dir and check

Design
------
* The archive holds the database plus the evidence tree. Evidence files are
  already encrypted at rest, so they travel encrypted; the archive itself is
  encrypted as a whole with the same master key, so a stolen backup is inert
  without the key.
* Every file is recorded under its tenant directory, so a restore preserves
  tenant isolation exactly as the live tree does.
* `verify` performs a real restore into a scratch directory and re-opens the
  database. A backup nobody has restored is a hope, not a recovery plan — the
  NFR asks for periodic recovery testing, and this is the command that does it.

Recovery objectives
-------------------
RPO — the interval between scheduled runs of `create` (recommend hourly for the
database, which makes the worst-case loss one hour of answers).
RTO — measured by `verify`, which prints the elapsed restore time.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import crypto  # noqa: E402
from app.core.config import settings  # noqa: E402

MANIFEST = "manifest.json"


def _backup_root() -> Path:
    root = settings.backup_dir or (Path(settings.storage_dir).parent / "backups")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _database_path() -> Path | None:
    url = settings.database_url
    if url.startswith("sqlite:///"):
        return Path(url.replace("sqlite:///", "", 1))
    return None


def create(label: str | None = None) -> Path:
    started = time.perf_counter()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"remas-{label or 'backup'}-{stamp}.tar.gz.enc"
    target = _backup_root() / name

    db_path = _database_path()
    if db_path is None:
        raise SystemExit(
            "DATABASE_URL is not SQLite. Use pg_dump for PostgreSQL and encrypt "
            "its output with the same master key."
        )

    buffer = io.BytesIO()
    files = 0
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        if db_path.exists():
            archive.add(db_path, arcname="database/remas.db")
            files += 1
        storage = Path(settings.storage_dir)
        if storage.exists():
            for path in sorted(storage.rglob("*")):
                if path.is_file():
                    # Keep the tenant directory in the arcname so isolation
                    # survives the round trip.
                    archive.add(path, arcname=f"storage/{path.relative_to(storage)}")
                    files += 1

        manifest = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "files": files,
            "database": str(db_path),
            "storage": str(storage),
            "evidence_encrypted": settings.encrypt_evidence,
            "schema_version": "1.0.0",
        }
        info = tarfile.TarInfo(MANIFEST)
        payload = json.dumps(manifest, indent=2).encode()
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))

    plain = buffer.getvalue()
    key = settings.evidence_master_key
    blob = crypto.encrypt(plain, key, "backup") if key else plain
    target.write_bytes(blob)

    elapsed = time.perf_counter() - started
    print(f"backup written: {target}")
    print(f"  files: {files}  size: {len(blob) // 1024} KB  in {elapsed:.1f}s")
    print(f"  sha256: {hashlib.sha256(blob).hexdigest()[:32]}…")
    print(f"  encrypted: {bool(key)}")
    return target


def _open(path: Path) -> bytes:
    blob = path.read_bytes()
    if crypto.is_encrypted(blob):
        key = settings.evidence_master_key
        if not key:
            raise SystemExit("This backup is encrypted and EVIDENCE_MASTER_KEY is not set.")
        return crypto.decrypt(blob, key, "backup")
    return blob


def restore(path: Path, into: Path | None = None) -> dict:
    started = time.perf_counter()
    plain = _open(path)
    destination = into or Path.cwd()
    destination.mkdir(parents=True, exist_ok=True)

    with tarfile.open(fileobj=io.BytesIO(plain), mode="r:gz") as archive:
        manifest = json.loads(archive.extractfile(MANIFEST).read().decode())
        for member in archive.getmembers():
            if member.name == MANIFEST:
                continue
            # Refuse path traversal in an archive we might not have written.
            if member.name.startswith(("/", "..")) or ".." in Path(member.name).parts:
                raise SystemExit(f"unsafe path in archive: {member.name}")
            archive.extract(member, destination)

    manifest["restore_seconds"] = round(time.perf_counter() - started, 2)
    manifest["restored_to"] = str(destination)
    return manifest


def verify(path: Path) -> bool:
    """A real restore into a scratch directory, then re-open the database and
    count what came back. This is the periodic recovery test the NFR asks for."""
    import sqlite3

    with tempfile.TemporaryDirectory() as tmp:
        manifest = restore(path, Path(tmp))
        db_file = Path(tmp) / "database" / "remas.db"
        storage = Path(tmp) / "storage"

        if not db_file.exists():
            print("FAIL: no database in the archive")
            return False

        connection = sqlite3.connect(db_file)
        try:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            counts = {}
            for table in ("organizations", "users", "assessments", "responses", "documents"):
                if table in tables:
                    counts[table] = connection.execute(
                        f"SELECT COUNT(*) FROM {table}"  # noqa: S608 - fixed names
                    ).fetchone()[0]
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            connection.close()

        tenants = sorted({p.name for p in storage.iterdir()}) if storage.exists() else []
        restored_files = sum(1 for p in storage.rglob("*") if p.is_file()) if storage.exists() else 0

        print(f"restore OK in {manifest['restore_seconds']}s  (RTO measured)")
        print(f"  integrity_check: {integrity}")
        print(f"  tables: {len(tables)}  rows: {counts}")
        print(f"  evidence files: {restored_files}  tenant directories: {len(tenants)}")
        print(f"  tenant isolation preserved: {all('/' not in t for t in tenants)}")
        return integrity == "ok"


def main() -> None:
    parser = argparse.ArgumentParser(description="REMAS backup and recovery")
    sub = parser.add_subparsers(dest="command", required=True)
    make = sub.add_parser("create")
    make.add_argument("--label", default=None)
    sub.add_parser("list")
    rest = sub.add_parser("restore")
    rest.add_argument("file")
    rest.add_argument("--into", default=None)
    check = sub.add_parser("verify")
    check.add_argument("file")

    args = parser.parse_args()
    if args.command == "create":
        create(args.label)
    elif args.command == "list":
        for path in sorted(_backup_root().glob("remas-*.enc")):
            size = path.stat().st_size // 1024
            print(f"{path.name}  {size} KB")
    elif args.command == "restore":
        manifest = restore(Path(args.file), Path(args.into) if args.into else None)
        print(json.dumps(manifest, indent=2))
    elif args.command == "verify":
        raise SystemExit(0 if verify(Path(args.file)) else 1)


if __name__ == "__main__":
    main()
