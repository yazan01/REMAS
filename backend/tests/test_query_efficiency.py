"""Query-count regression tests.

An N+1 is invisible in review and obvious in a count, so these tests measure
rather than inspect. They exist because `GET /assessments` — the customer's main
dashboard call — was measured at 10 queries for one assessment and 34 for four,
i.e. eight per row, and nothing in the code or the test suite said so.

The equivalence test matters more than the count: the batched path must agree
with the detail computation to the digit, or a customer sees one completion
percentage on the dashboard and a different one inside the assessment.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.core.config import settings
from app.db.base import Base
from app.db.seed import load_framework, load_roadmap_content, seed_accounts
from app.db.session import SessionLocal, engine, init_db
from app.main import app
from app.services import assessment_service

API = settings.api_prefix
PASSWORD = "Remas#2026"


class QueryCounter:
    """Counts statements issued while the block is open."""

    def __init__(self) -> None:
        self.count = 0

    def __enter__(self) -> "QueryCounter":
        self.count = 0
        event.listen(engine, "before_cursor_execute", self._tick)
        return self

    def __exit__(self, *exc: object) -> bool:
        event.remove(engine, "before_cursor_execute", self._tick)
        return False

    def _tick(self, *args: object, **kwargs: object) -> None:
        self.count += 1


@pytest.fixture(scope="module")
def client():
    from app import models  # noqa: F401

    Base.metadata.drop_all(bind=engine)
    init_db()
    with SessionLocal() as db:
        version = load_framework(db)
        load_roadmap_content(db, version)
        seed_accounts(db)
        db.commit()
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="module")
def owner(client):
    token = client.post(
        f"{API}/auth/login",
        json={"email": "owner@demodeveloper.com", "password": PASSWORD},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def framework(client, owner):
    return client.get(f"{API}/frameworks/current", headers=owner).json()


def _create(client, owner, framework, name: str, axis_count: int = 4) -> str:
    return client.post(
        f"{API}/assessments",
        json={
            "name": name,
            "framework_version_id": framework["id"],
            "layer": "quick_score",
            "axis_ids": [a["id"] for a in framework["axes"][:axis_count]],
        },
        headers=owner,
    ).json()["id"]


def test_listing_assessments_does_not_grow_with_the_number_of_rows(
    client, owner, framework
) -> None:
    """The regression this file exists for.

    Before batching: 10 queries for one assessment, 34 for four. After: a fixed
    cost. The assertion is on the *growth*, not on an exact number, so a future
    change that adds one legitimate query does not fail the build spuriously.
    """
    _create(client, owner, framework, "efficiency-1")
    with QueryCounter() as counter:
        client.get(f"{API}/assessments", headers=owner)
    with_one = counter.count

    for i in range(2, 6):
        _create(client, owner, framework, f"efficiency-{i}")
    with QueryCounter() as counter:
        response = client.get(f"{API}/assessments", headers=owner)
    with_five = counter.count

    assert len(response.json()) >= 5
    assert with_five <= with_one + 2, (
        f"query count grew with the row count: {with_one} for 1 assessment, "
        f"{with_five} for 5 — this is an N+1"
    )


def test_batched_completion_matches_the_detail_computation(client, owner, framework) -> None:
    """The batched list path and `progress()` must agree exactly.

    They are two code paths over the same rule. If they diverge, the dashboard
    and the questionnaire header show different percentages for the same
    assessment and nobody can tell which is right.
    """
    assessment_id = _create(client, owner, framework, "equivalence", axis_count=3)
    questions = client.get(
        f"{API}/assessments/{assessment_id}/questions", headers=owner
    ).json()
    # Answer a partial, awkward subset: some scored, one not-applicable.
    answered = questions[:7]
    for index, question in enumerate(answered):
        body = (
            {"question_id": question["question_id"], "is_not_applicable": True,
             "na_rationale": "خارج النطاق"}
            if index == 0
            else {"question_id": question["question_id"], "score": 3}
        )
        client.put(
            f"{API}/assessments/{assessment_id}/responses", json=[body], headers=owner
        )

    listed = next(
        item
        for item in client.get(f"{API}/assessments", headers=owner).json()
        if item["id"] == assessment_id
    )
    detail = client.get(
        f"{API}/assessments/{assessment_id}/progress", headers=owner
    ).json()

    assert listed["completion"] == detail["completion"], (
        "the batched list completion diverged from progress(): "
        f"{listed['completion']} vs {detail['completion']}"
    )
    assert 0 < listed["completion"] < 1, "the fixture should be partially answered"


def test_batched_completion_handles_an_empty_list() -> None:
    with SessionLocal() as db:
        assert assessment_service.completion_for_many(db, []) == {}
        assert assessment_service.latest_runs_for_many(db, []) == {}


def test_admin_framework_listing_does_not_grow_with_the_axis_count(client) -> None:
    """The count columns used to lazy-load per version and per axis: 20 queries
    for one 16-axis framework, and one more for every axis added."""
    token = client.post(
        f"{API}/auth/login",
        json={"email": "admin@ivalueconsult.com", "password": PASSWORD},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    with QueryCounter() as counter:
        response = client.get(f"{API}/admin/frameworks", headers=headers)
    axes = sum(v["axis_count"] for f in response.json() for v in f["versions"])
    assert axes >= 16, "the seeded framework should have its 16 pillars"
    assert counter.count <= 6, (
        f"{counter.count} queries for {axes} axes — the counts are lazy-loading again"
    )


def test_admin_user_register_stays_flat(client) -> None:
    """A cross-tenant register is the natural place for an N+1 to appear, so
    the count is pinned here too."""
    token = client.post(
        f"{API}/auth/login",
        json={"email": "admin@ivalueconsult.com", "password": PASSWORD},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    with QueryCounter() as counter:
        client.get(f"{API}/admin/users", headers=headers)
    assert counter.count <= 4, f"{counter.count} queries for the user register"
