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
from app.models import (
    DEFAULT_BRANDING,
    DEFAULT_SECTIONS,
    InitiativeTemplate,
    ReportTemplate,
    RoadmapHorizon,
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


HORIZONS = [
    ("immediate", "أولويات فورية", "Immediate priorities", 0, 3),
    ("short", "المدى القصير", "Short term", 3, 6),
    ("medium", "المدى المتوسط", "Medium term", 6, 12),
    ("long", "المدى الطويل", "Long term", 12, 24),
]

# Starter initiative library. Matched to an axis score band, so a pillar scoring
# 1.8 draws the foundational initiative and one scoring 4.2 draws the optimising
# one. Replaced wholesale by iValue's approved library.
INITIATIVE_LIBRARY = [
    {
        "code": "INIT-FOUND",
        "title_ar": "تأسيس السياسة والإجراء الأساسيين للمحور",
        "title_en": "Establish the pillar's core policy and procedure",
        "objective_ar": "إيجاد مرجعية مكتوبة ومعتمدة تحكم الممارسة وتحدد المسؤوليات.",
        "objective_en": "Create an approved written reference governing the practice and its ownership.",
        "rationale_ar": "درجة المحور تقع في النطاق التأسيسي، ما يعني غياب مرجعية موثّقة.",
        "rationale_en": "The pillar scores in the initial band, indicating no documented reference exists.",
        "owner_function_ar": "الإدارة المالكة للمحور بالتنسيق مع إدارة الحوكمة",
        "owner_function_en": "The owning function with the governance office",
        "dependencies_ar": "اعتماد الإدارة العليا وتعيين مالك للمحور.",
        "dependencies_en": "Executive approval and a named pillar owner.",
        "applies_min_score": 1.0,
        "applies_max_score": 2.49,
        "default_horizon_code": "immediate",
        "effort": "medium",
    },
    {
        "code": "INIT-OWNER",
        "title_ar": "تعيين مالك للمحور ومصفوفة مسؤوليات",
        "title_en": "Assign a pillar owner and a responsibility matrix",
        "objective_ar": "إسناد المسؤولية بوضوح ومنع تشتت التنفيذ بين الإدارات.",
        "objective_en": "Assign responsibility clearly and stop execution scattering across functions.",
        "rationale_ar": "الممارسات متفرقة وغير مسندة لجهة واحدة.",
        "rationale_en": "Practices are scattered with no single accountable function.",
        "owner_function_ar": "الموارد البشرية والتطوير المؤسسي",
        "owner_function_en": "HR and organisational development",
        "applies_min_score": 1.0,
        "applies_max_score": 2.99,
        "default_horizon_code": "immediate",
        "effort": "low",
    },
    {
        "code": "INIT-STANDARD",
        "title_ar": "توحيد الإجراءات وتوثيقها ونشرها",
        "title_en": "Standardise, document and publish the procedures",
        "objective_ar": "الانتقال من تطبيق جزئي إلى إجراء موحّد معروف لدى المنفذين.",
        "objective_en": "Move from partial application to one standard procedure known to its users.",
        "rationale_ar": "التطبيق منظّم جزئياً وتظهر فجوات في الانتظام والتوثيق.",
        "rationale_en": "Implementation is partly organised with gaps in consistency and documentation.",
        "owner_function_ar": "إدارة التميز المؤسسي",
        "owner_function_en": "Corporate excellence",
        "dependencies_ar": "اكتمال السياسة الأساسية للمحور.",
        "dependencies_en": "The pillar's core policy in place.",
        "applies_min_score": 2.5,
        "applies_max_score": 3.99,
        "default_horizon_code": "short",
        "effort": "medium",
    },
    {
        "code": "INIT-KPI",
        "title_ar": "بناء مؤشرات أداء للمحور ودورية مراجعة معلنة",
        "title_en": "Build pillar KPIs and a published review cycle",
        "objective_ar": "قياس الأداء دورياً وربطه بقرارات التحسين.",
        "objective_en": "Measure performance periodically and tie it to improvement decisions.",
        "rationale_ar": "المتابعة غير منتظمة ولا تستند إلى مؤشرات معتمدة.",
        "rationale_en": "Monitoring is irregular and not based on approved indicators.",
        "owner_function_ar": "إدارة الأداء المؤسسي",
        "owner_function_en": "Corporate performance",
        "applies_min_score": 2.5,
        "applies_max_score": 4.49,
        "default_horizon_code": "medium",
        "effort": "medium",
    },
    {
        "code": "INIT-AUTOMATE",
        "title_ar": "أتمتة المحور وربطه بلوحة الأداء المؤسسية",
        "title_en": "Automate the pillar and link it to the corporate dashboard",
        "objective_ar": "تقليل الاعتماد على العمل اليدوي وإتاحة القياس اللحظي.",
        "objective_en": "Reduce manual effort and enable real-time measurement.",
        "rationale_ar": "الممارسة ناضجة ويمكن رفع كفاءتها بالأتمتة والقياس المستمر.",
        "rationale_en": "The practice is mature; automation and continuous measurement raise its efficiency.",
        "owner_function_ar": "إدارة التحول الرقمي",
        "owner_function_en": "Digital transformation",
        "dependencies_ar": "وجود إجراء موحّد ومؤشرات معتمدة.",
        "dependencies_en": "A standard procedure and approved indicators.",
        "applies_min_score": 3.5,
        "applies_max_score": 5.0,
        "default_horizon_code": "long",
        "effort": "high",
    },
]


def load_roadmap_content(db: Session, version: FrameworkVersion) -> None:
    """Seed the delivery horizons (FR-29) and the initiative library (FR-28)."""
    existing = db.scalar(
        select(RoadmapHorizon).where(RoadmapHorizon.framework_version_id == version.id)
    )
    if existing is None:
        for index, (code, name_ar, name_en, start, end) in enumerate(HORIZONS):
            db.add(
                RoadmapHorizon(
                    framework_version_id=version.id,
                    code=code,
                    order_index=index,
                    name_ar=name_ar,
                    name_en=name_en,
                    months_from=start,
                    months_to=end,
                )
            )

    has_templates = db.scalar(
        select(InitiativeTemplate).where(
            InitiativeTemplate.framework_version_id == version.id
        )
    )
    if has_templates is None:
        for template in INITIATIVE_LIBRARY:
            db.add(InitiativeTemplate(framework_version_id=version.id, **template))
    # FR-34 - a default report template so the report is configuration-driven
    # from the first run rather than falling back to built-in constants.
    has_template = db.scalar(
        select(ReportTemplate).where(
            ReportTemplate.framework_version_id == version.id
        )
    )
    if has_template is None:
        db.add(
            ReportTemplate(
                framework_version_id=version.id,
                code="standard",
                name_ar="قالب التقرير المعتمد",
                name_en="Approved report template",
                is_default=True,
                sections=list(DEFAULT_SECTIONS),
                branding=dict(DEFAULT_BRANDING),
                copy_blocks={},
                output_formats=["pdf", "html", "json"],
                maturity_labels={},
                include_comparison=True,
            )
        )

    db.flush()
    print(
        f"loaded {len(HORIZONS)} horizons, {len(INITIATIVE_LIBRARY)} initiative "
        f"templates and the default report template"
    )


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
        version = load_framework(db)
        load_roadmap_content(db, version)
        seed_accounts(db)
        db.commit()

    print("\ndemo accounts (password: %s)" % DEMO_PASSWORD)
    print("  admin@ivalueconsult.com     — iValue administrator")
    print("  reviewer@ivalueconsult.com  — iValue reviewer")
    print("  owner@demodeveloper.com       — customer organisation owner")


if __name__ == "__main__":
    main()
