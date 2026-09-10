"""The lifecycle rules for an assessment framework version (FR-32, FR-35).

Three rules used to be spread across two controllers:

* which published version is "the current one" — lived in the frameworks route
  and was imported by the assessments and catalogue routes;
* a published version is immutable — lived in the admin route as `_editable`;
* what a brand-new version starts with — lived in the admin route as two
  `_seed_*` helpers.

They belong together because they are one thing: the rules that govern a
version's life from creation to publication. Keeping them in a controller meant
any other caller had to import an HTTP module to ask a domain question.
"""

from __future__ import annotations

from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.errors import APIError
from app.models import (
    Axis,
    Framework,
    FrameworkStatus,
    FrameworkVersion,
    MaturityLevel,
    RoadmapHorizon,
)

#: The 1-5 scale from BRD §6.5. Seeded into every new version so an
#: administrator starts from the approved wording rather than an empty table.
DEFAULT_MATURITY_LEVELS: tuple[tuple[int, str, str], ...] = (
    (1, "تأسيسي", "Initial"),
    (2, "ناشئ", "Developing"),
    (3, "مُعرَّف", "Defined"),
    (4, "مُدار", "Managed"),
    (5, "متميّز", "Distinguished"),
)

#: The delivery horizons from FR-29. Labels and periods stay configurable.
DEFAULT_HORIZONS: tuple[tuple[str, str, str, int, int], ...] = (
    ("immediate", "أولويات فورية", "Immediate priorities", 0, 3),
    ("short", "المدى القصير", "Short term", 3, 6),
    ("medium", "المدى المتوسط", "Medium term", 6, 12),
    ("long", "المدى الطويل", "Long term", 12, 24),
)


def load_version(db: Session, version_id: str) -> FrameworkVersion:
    version = db.get(FrameworkVersion, version_id)
    if version is None:
        raise APIError("framework.not_found", status.HTTP_404_NOT_FOUND)
    return version


def assert_editable(version: FrameworkVersion) -> FrameworkVersion:
    """FR-35 — a published version is frozen.

    Editing means cloning to a new draft and publishing that, which is what
    keeps a historical assessment reproducible against the exact content it was
    answered under.
    """
    if version.status != FrameworkStatus.DRAFT:
        raise APIError("framework.version_locked", status.HTTP_409_CONFLICT)
    return version


def current_published_version(db: Session, code: str | None = None) -> FrameworkVersion:
    """The live version of one framework.

    Several frameworks can be published at once (FR-32), so "current" is scoped
    by framework code — defaulting to `settings.default_framework_code` — rather
    than meaning "whichever was published last", which would silently swap the
    questionnaire under customers the moment a second tool went live.
    """

    def query(framework_code: str | None) -> FrameworkVersion | None:
        stmt = (
            select(FrameworkVersion)
            .join(Framework)
            .where(
                FrameworkVersion.status == FrameworkStatus.PUBLISHED,
                Framework.is_active.is_(True),
            )
            .options(
                selectinload(FrameworkVersion.axes).selectinload(Axis.questions),
                selectinload(FrameworkVersion.maturity_levels),
                selectinload(FrameworkVersion.framework),
            )
            .order_by(FrameworkVersion.published_at.desc())
        )
        if framework_code:
            stmt = stmt.where(Framework.code == framework_code)
        return db.scalars(stmt).first()

    version = query(code or settings.default_framework_code)
    if version is None and code is None:
        # A deployment that renamed its framework still gets a sensible answer.
        version = query(None)
    if version is None:
        raise APIError("framework.no_published_version", status.HTTP_404_NOT_FOUND)
    return version


def seed_default_levels(db: Session, version: FrameworkVersion) -> None:
    for score, label_ar, label_en in DEFAULT_MATURITY_LEVELS:
        db.add(
            MaturityLevel(
                framework_version_id=version.id,
                score=score,
                label_ar=label_ar,
                label_en=label_en,
            )
        )


def seed_default_horizons(db: Session, version: FrameworkVersion) -> None:
    for index, (code, name_ar, name_en, start, end) in enumerate(DEFAULT_HORIZONS):
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
