"""Seed the database with the framework content and a demo tenant.

Run from the backend directory:

    python -m app.db.seed            # content + demo accounts
    python -m app.db.seed --reset    # drop and rebuild first
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password, utcnow
from app.db.base import Base
from app.db.session import SessionLocal, engine, init_db
from app.models import (
    Axis,
    Framework,
    FrameworkVersion,
    MaturityLevel,
    Organization,
    Question,
    User,
)
from app.models.enums import FrameworkStatus, Locale, UserRole

SEED_FILE = Path(__file__).parent / "seed_data" / "remas_v1.json"

DEMO_PASSWORD = "Remas#2026"


def load_framework(db: Session, path: Path = SEED_FILE) -> FrameworkVersion:
    data = json.loads(path.read_text(encoding="utf-8"))
    meta = data["framework"]

    framework = db.scalar(select(Framework).where(Framework.code == meta["code"]))
    if framework is None:
        framework = Framework(**meta)
        db.add(framework)
        db.flush()

    existing = db.scalar(
        select(FrameworkVersion).where(
            FrameworkVersion.framework_id == framework.id,
            FrameworkVersion.version == data["version"],
        )
    )
    if existing:
        print(f"framework version {data['version']} already present — skipping content")
        return existing

    version = FrameworkVersion(
        framework_id=framework.id,
        version=data["version"],
        status=FrameworkStatus.PUBLISHED,
        published_at=utcnow(),
        source_note=data.get("source_note"),
    )
    db.add(version)
    db.flush()

    for level in data["maturity_levels"]:
        db.add(MaturityLevel(framework_version_id=version.id, **level))

    for axis_index, axis_data in enumerate(data["axes"], start=1):
        questions = axis_data.pop("questions", [])
        axis = Axis(framework_version_id=version.id, order_index=axis_index, **axis_data)
        db.add(axis)
        db.flush()
        for q_index, q in enumerate(questions, start=1):
            db.add(Question(axis_id=axis.id, order_index=q_index, **q))

    db.flush()
    print(
        f"loaded framework {framework.code} {version.version}: "
        f"{len(data['axes'])} axes, "
        f"{sum(1 for _ in db.scalars(select(Question).join(Axis).where(Axis.framework_version_id == version.id)))} questions"
    )
    return version


def _ensure_user(
    db: Session, *, org: Organization, email: str, name: str, role: UserRole, locale: str
) -> User:
    user = db.scalar(select(User).where(User.email == email))
    if user:
        return user
    user = User(
        organization_id=org.id,
        email=email,
        password_hash=hash_password(DEMO_PASSWORD),
        full_name=name,
        role=role,
        locale=locale,
        email_verified_at=utcnow(),
    )
    db.add(user)
    db.flush()
    return user


def seed_accounts(db: Session) -> None:
    ivalue = db.scalar(select(Organization).where(Organization.slug == "ivalue"))
    if ivalue is None:
        ivalue = Organization(
            slug="ivalue",
            name_ar="آي فاليو للاستشارات",
            name_en="iValue Consult",
            is_ivalue=True,
            country="Saudi Arabia",
        )
        db.add(ivalue)
        db.flush()

    demo = db.scalar(select(Organization).where(Organization.slug == "demo-developer"))
    if demo is None:
        demo = Organization(
            slug="demo-developer",
            name_ar="شركة تطوير تجريبية",
            name_en="Demo Development Company",
            city="الرياض",
            country="Saudi Arabia",
            employee_count=180,
            years_active=12,
            primary_segment="سكني",
        )
        db.add(demo)
        db.flush()

    _ensure_user(
        db,
        org=ivalue,
        email="admin@ivalueconsult.com",
        name="مسؤول iValue",
        role=UserRole.IVALUE_ADMIN,
        locale=Locale.AR,
    )
    _ensure_user(
        db,
        org=ivalue,
        email="reviewer@ivalueconsult.com",
        name="مراجع iValue",
        role=UserRole.IVALUE_REVIEWER,
        locale=Locale.AR,
    )
    _ensure_user(
        db,
        org=demo,
        email="owner@demodeveloper.com",
        name="مالك الحساب التجريبي",
        role=UserRole.ORG_OWNER,
        locale=Locale.AR,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the REMAS database")
    parser.add_argument("--reset", action="store_true", help="drop all tables first")
    args = parser.parse_args()

    if args.reset:
        import app.models  # noqa: F401

        Base.metadata.drop_all(bind=engine)
        print("dropped all tables")

    init_db()
    with SessionLocal() as db:
        load_framework(db)
        seed_accounts(db)
        db.commit()

    print("\ndemo accounts (password: %s)" % DEMO_PASSWORD)
    print("  admin@ivalueconsult.com     — iValue administrator")
    print("  reviewer@ivalueconsult.com  — iValue reviewer")
    print("  owner@demodeveloper.com       — customer organisation owner")


if __name__ == "__main__":
    main()
