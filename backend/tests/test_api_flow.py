"""End-to-end flow over the HTTP API: register -> verify -> login -> assess ->
submit -> results, plus the tenant isolation gate."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

TMP_DB = Path(tempfile.gettempdir()) / "remas_test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TMP_DB}"

from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.seed import load_framework, seed_accounts  # noqa: E402
from app.db.session import SessionLocal, engine, init_db  # noqa: E402
from app.main import app  # noqa: E402

API = settings.api_prefix


@pytest.fixture(scope="module")
def client():
    from app import models  # noqa: F401  (registers mappers; `import app.models`
    # would shadow the FastAPI `app` imported above)

    Base.metadata.drop_all(bind=engine)
    init_db()
    with SessionLocal() as db:
        load_framework(db)
        seed_accounts(db)
        db.commit()
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(bind=engine)


def login(client, email: str, password: str = "Remas#2026") -> dict:
    res = client.post(f"{API}/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def test_registration_requires_email_verification(client):
    payload = {
        "email": "new.owner@newdeveloper.com",
        "password": "Str0ngPass!23",
        "full_name": "مالك جديد",
        "organization_name_ar": "شركة الاختبار",
        "organization_name_en": "Test Developments",
    }
    res = client.post(f"{API}/auth/register", json=payload)
    assert res.status_code == 201, res.text

    denied = client.post(
        f"{API}/auth/login", json={"email": payload["email"], "password": payload["password"]}
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "auth.email_not_verified"
    # Errors carry both languages so the UI toggle needs no second request.
    assert denied.json()["message_ar"] and denied.json()["message_en"]

    token = client.get(
        f"{API}/auth/dev/verification-token", params={"email": payload["email"]}
    ).json()["token"]
    verified = client.post(f"{API}/auth/verify", json={"token": token})
    assert verified.status_code == 200
    assert verified.json()["access_token"]


def test_duplicate_email_is_rejected(client):
    res = client.post(
        f"{API}/auth/register",
        json={
            "email": "owner@demodeveloper.com",
            "password": "Str0ngPass!23",
            "full_name": "مكرر",
            "organization_name_ar": "مكرر",
            "organization_name_en": "Duplicate",
        },
    )
    assert res.status_code == 409
    assert res.json()["code"] == "auth.email_taken"


def test_content_is_returned_in_both_languages(client):
    headers = login(client, "owner@demodeveloper.com")
    res = client.get(f"{API}/frameworks/current", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["axis_count"] == 16
    assert body["question_count"] == 160  # BRD: 16 pillars x 10 questions
    axis = body["axes"][0]
    assert axis["name_ar"] and axis["name_en"]
    assert axis["questions"][0]["text_ar"] and axis["questions"][0]["text_en"]
    assert {level["score"] for level in body["maturity_levels"]} == {1, 2, 3, 4, 5}


def test_full_assessment_lifecycle(client):
    headers = login(client, "owner@demodeveloper.com")
    framework = client.get(f"{API}/frameworks/current", headers=headers).json()
    two_axes = [framework["axes"][0], framework["axes"][1]]

    created = client.post(
        f"{API}/assessments",
        headers=headers,
        json={
            "name": "تقييم 2026",
            "layer": "quick_score",
            "selected_axis_ids": [a["id"] for a in two_axes],
        },
    )
    assert created.status_code == 201, created.text
    assessment_id = created.json()["id"]

    questions = [q for a in two_axes for q in a["questions"]]
    assert len(questions) == 20  # two pillars, ten questions each

    # Partial save -> cannot submit yet.
    client.put(
        f"{API}/assessments/{assessment_id}/responses",
        headers=headers,
        json=[{"question_id": questions[0]["id"], "score": 4}],
    ).raise_for_status()

    progress = client.get(f"{API}/assessments/{assessment_id}/progress", headers=headers).json()
    assert progress["answered_questions"] == 1
    assert progress["can_submit"] is False

    blocked = client.post(f"{API}/assessments/{assessment_id}/submit", headers=headers)
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "assessment.mandatory_incomplete"

    # Answer the rest: 4s everywhere, one "not applicable" with a rationale.
    batch = [{"question_id": q["id"], "score": 4} for q in questions[1:-1]]
    batch.append(
        {
            "question_id": questions[-1]["id"],
            "is_not_applicable": True,
            "na_rationale": "لا ينطبق على نموذج عمل المنشأة",
        }
    )
    saved = client.put(
        f"{API}/assessments/{assessment_id}/responses", headers=headers, json=batch
    )
    assert saved.status_code == 200, saved.text

    progress = client.get(f"{API}/assessments/{assessment_id}/progress", headers=headers).json()
    assert progress["can_submit"] is True
    assert progress["completion"] == 1.0

    result = client.post(f"{API}/assessments/{assessment_id}/submit", headers=headers)
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["overall_score"] == 4.0
    assert body["maturity_level"] == 4
    assert len(body["axes"]) == 2
    assert body["priorities"][0]["rank"] == 1

    # Submitted assessments are closed for editing.
    reopened = client.put(
        f"{API}/assessments/{assessment_id}/responses",
        headers=headers,
        json=[{"question_id": questions[0]["id"], "score": 1}],
    )
    assert reopened.status_code == 409
    assert reopened.json()["code"] == "assessment.already_submitted"


def test_not_applicable_requires_a_rationale(client):
    headers = login(client, "owner@demodeveloper.com")
    framework = client.get(f"{API}/frameworks/current", headers=headers).json()
    axis = framework["axes"][2]
    created = client.post(
        f"{API}/assessments",
        headers=headers,
        json={"name": "تقييم المبرر", "selected_axis_ids": [axis["id"]]},
    ).json()

    res = client.put(
        f"{API}/assessments/{created['id']}/responses",
        headers=headers,
        json=[{"question_id": axis["questions"][0]["id"], "is_not_applicable": True}],
    )
    assert res.status_code == 422
    assert res.json()["code"] == "validation.failed"
    assert "مبرر" in res.json()["message_ar"]


def test_reviewer_override_is_recorded_beside_the_customer_answer(client):
    owner = login(client, "owner@demodeveloper.com")
    reviewer = login(client, "reviewer@ivalueconsult.com")
    framework = client.get(f"{API}/frameworks/current", headers=owner).json()
    axis = framework["axes"][3]
    assessment = client.post(
        f"{API}/assessments",
        headers=owner,
        json={"name": "تقييم المراجعة", "selected_axis_ids": [axis["id"]]},
    ).json()
    question = axis["questions"][0]

    client.put(
        f"{API}/assessments/{assessment['id']}/responses",
        headers=owner,
        json=[{"question_id": question["id"], "score": 5}],
    ).raise_for_status()

    # A customer cannot override.
    denied = client.post(
        f"{API}/assessments/{assessment['id']}/questions/{question['id']}/override",
        headers=owner,
        json={"score": 2, "reason": "محاولة غير مصرّح بها"},
    )
    assert denied.status_code == 403

    applied = client.post(
        f"{API}/assessments/{assessment['id']}/questions/{question['id']}/override",
        headers=reviewer,
        json={"score": 2, "reason": "الدليل المرفق لا يدعم الدرجة المُدخلة"},
    )
    assert applied.status_code == 200, applied.text
    body = applied.json()
    assert body["score"] == 5           # the customer's answer is preserved
    assert body["override_score"] == 2  # the reviewer's decision sits beside it
    assert body["effective_score"] == 2


def test_tenant_isolation(client):
    owner = login(client, "owner@demodeveloper.com")
    framework = client.get(f"{API}/frameworks/current", headers=owner).json()
    assessment = client.post(
        f"{API}/assessments",
        headers=owner,
        json={"name": "خاص", "selected_axis_ids": [framework["axes"][4]["id"]]},
    ).json()

    outsider = client.post(
        f"{API}/auth/register",
        json={
            "email": "outsider@otherdeveloper.com",
            "password": "Str0ngPass!23",
            "full_name": "مستخدم آخر",
            "organization_name_ar": "منشأة أخرى",
            "organization_name_en": "Other Org",
        },
    )
    assert outsider.status_code == 201
    token = client.get(
        f"{API}/auth/dev/verification-token", params={"email": "outsider@otherdeveloper.com"}
    ).json()["token"]
    other = {
        "Authorization": "Bearer "
        + client.post(f"{API}/auth/verify", json={"token": token}).json()["access_token"]
    }

    # Another tenant gets 404, not 403 — the API never confirms the record exists.
    res = client.get(f"{API}/assessments/{assessment['id']}", headers=other)
    assert res.status_code == 404
    assert client.get(f"{API}/assessments", headers=other).json() == []


def test_unauthenticated_requests_are_rejected(client):
    res = client.get(f"{API}/assessments")
    assert res.status_code == 401
    assert res.json()["code"] == "auth.not_authenticated"
