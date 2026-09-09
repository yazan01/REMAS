"""Coverage for the phases completed after the first release: account security,
the administration portal, the AI pipeline, initiatives/roadmap and reporting."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.db.base import Base
from app.db.seed import load_framework, load_roadmap_content, seed_accounts
from app.db.session import SessionLocal, engine, init_db
from app.main import app

API = settings.api_prefix
PASSWORD = "Remas#2026"


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


def auth(client, email: str, password: str = PASSWORD) -> dict:
    res = client.post(f"{API}/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture(scope="module")
def owner(client):
    return auth(client, "owner@demodeveloper.com")


@pytest.fixture(scope="module")
def reviewer(client):
    return auth(client, "reviewer@ivalueconsult.com")


@pytest.fixture(scope="module")
def admin(client):
    return auth(client, "admin@ivalueconsult.com")


def _complete_assessment(client, headers, name: str, axis_count: int = 3, layer="ai_report"):
    """Create an assessment, answer every question and submit it."""
    framework = client.get(f"{API}/frameworks/current", headers=headers).json()
    axes = framework["axes"][:axis_count]
    created = client.post(
        f"{API}/assessments",
        headers=headers,
        json={"name": name, "layer": layer, "selected_axis_ids": [a["id"] for a in axes]},
    )
    assert created.status_code == 201, created.text
    assessment_id = created.json()["id"]

    questions = [q for a in axes for q in a["questions"]]
    batch = [{"question_id": q["id"], "score": (i % 5) + 1} for i, q in enumerate(questions)]
    saved = client.put(
        f"{API}/assessments/{assessment_id}/responses", headers=headers, json=batch
    )
    assert saved.status_code == 200, saved.text
    submitted = client.post(f"{API}/assessments/{assessment_id}/submit", headers=headers)
    assert submitted.status_code == 200, submitted.text
    return assessment_id, axes, questions


# ─────────────────────────── account security ──────────────────────────────


def test_password_reset_round_trip(client):
    email = "reset.user@newdeveloper.com"
    client.post(
        f"{API}/auth/register",
        json={
            "email": email,
            "password": "Str0ngPass!23",
            "full_name": "مستخدم الاستعادة",
            "organization_name_ar": "منشأة الاستعادة",
            "organization_name_en": "Reset Org",
        },
    ).raise_for_status()

    # The request endpoint must not reveal whether an address exists.
    unknown = client.post(
        f"{API}/account/password/reset-request", json={"email": "nobody@nowhere-example.com"}
    )
    assert unknown.status_code == 202

    client.post(f"{API}/account/password/reset-request", json={"email": email}).raise_for_status()
    token = client.get(f"{API}/account/password/dev-token", params={"email": email}).json()["token"]

    res = client.post(f"{API}/account/password/reset", json={"token": token, "password": "N3wPass!2026"})
    assert res.status_code == 200
    assert res.json()["access_token"]

    # The reset also verifies the mailbox, so the new password logs in directly.
    assert auth(client, email, "N3wPass!2026")
    # ...and the token is single-use.
    assert client.post(
        f"{API}/account/password/reset", json={"token": token, "password": "Another!2026"}
    ).status_code == 400


def test_mfa_enrol_confirm_and_login(client):
    import pyotp

    email = "mfa.user@newdeveloper.com"
    client.post(
        f"{API}/auth/register",
        json={
            "email": email,
            "password": "Str0ngPass!23",
            "full_name": "مستخدم التحقق",
            "organization_name_ar": "منشأة التحقق",
            "organization_name_en": "MFA Org",
        },
    ).raise_for_status()
    verify_token = client.get(
        f"{API}/auth/dev/verification-token", params={"email": email}
    ).json()["token"]
    client.post(f"{API}/auth/verify", json={"token": verify_token}).raise_for_status()

    headers = auth(client, email, "Str0ngPass!23")
    enrol = client.post(f"{API}/account/mfa/enrol", headers=headers)
    assert enrol.status_code == 200
    secret = enrol.json()["secret"]
    assert enrol.json()["otpauth_uri"].startswith("otpauth://totp/")

    assert client.post(
        f"{API}/account/mfa/confirm", headers=headers, json={"code": "000000"}
    ).status_code == 401

    code = pyotp.TOTP(secret).now()
    assert client.post(
        f"{API}/account/mfa/confirm", headers=headers, json={"code": code}
    ).status_code == 204

    # Login now demands the second factor.
    denied = client.post(f"{API}/auth/login", json={"email": email, "password": "Str0ngPass!23"})
    assert denied.status_code == 401
    assert denied.json()["code"] == "auth.mfa_required"

    ok = client.post(
        f"{API}/auth/login",
        json={"email": email, "password": "Str0ngPass!23", "mfa_code": pyotp.TOTP(secret).now()},
    )
    assert ok.status_code == 200


def test_admin_cannot_disable_mfa(client, admin):
    client.post(f"{API}/account/mfa/enrol", headers=admin).raise_for_status()
    res = client.request("DELETE", f"{API}/account/mfa", headers=admin, json={"code": "123456"})
    assert res.status_code == 403
    assert res.json()["code"] == "auth.mfa_required_for_role"


def test_invitation_flow(client, owner):
    invited = client.post(
        f"{API}/account/invitations", headers=owner,
        json={"email": "colleague@demodeveloper.com", "role": "contributor"},
    )
    assert invited.status_code == 201

    token = client.get(
        f"{API}/account/invitations/dev-token", params={"email": "colleague@demodeveloper.com"}
    ).json()["token"]
    accepted = client.post(
        f"{API}/account/invitations/accept",
        json={"token": token, "full_name": "زميل", "password": "Str0ngPass!23"},
    )
    assert accepted.status_code == 200

    members = client.get(f"{API}/account/members", headers=owner).json()
    assert any(m["email"] == "colleague@demodeveloper.com" for m in members)
    # An invitation cannot be redeemed twice.
    assert client.post(
        f"{API}/account/invitations/accept",
        json={"token": token, "full_name": "مكرر", "password": "Str0ngPass!23"},
    ).status_code in (400, 409)


def test_customer_admin_cannot_mint_an_ivalue_reviewer(client, owner):
    res = client.post(
        f"{API}/account/invitations", headers=owner,
        json={"email": "escalation@demodeveloper.com", "role": "ivalue_reviewer"},
    )
    assert res.status_code == 403


# ────────────────────────── administration portal ──────────────────────────


def test_published_version_is_immutable_and_clone_unlocks_editing(client, admin):
    frameworks = client.get(f"{API}/admin/frameworks", headers=admin).json()
    published = next(
        v for f in frameworks for v in f["versions"] if v["status"] == "published"
    )

    blocked = client.post(
        f"{API}/admin/versions/{published['id']}/axes",
        headers=admin,
        json={"code": "AXNEW", "name_ar": "محور", "name_en": "Axis"},
    )
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "framework.version_locked"

    clone = client.post(
        f"{API}/admin/versions/{published['id']}/clone",
        headers=admin,
        json={"version": "1.1-draft"},
    )
    assert clone.status_code == 201
    draft_id = clone.json()["version_id"]

    added = client.post(
        f"{API}/admin/versions/{draft_id}/axes",
        headers=admin,
        json={"code": "AXNEW", "name_ar": "محور جديد", "name_en": "New pillar", "weight": 1.0},
    )
    assert added.status_code == 201

    question = client.post(
        f"{API}/admin/axes/{added.json()['axis_id']}/questions",
        headers=admin,
        json={"code": "AXNEW-Q1", "text_ar": "سؤال", "text_en": "Question", "weight": 1.0},
    )
    assert question.status_code == 201

    # The clone carried the content across.
    detail = client.get(f"{API}/frameworks/versions/{draft_id}", headers=admin).json()
    assert detail["axis_count"] == 17
    assert detail["question_count"] == 161


def test_scoring_config_is_configurable_and_validated(client, admin):
    frameworks = client.get(f"{API}/admin/frameworks", headers=admin).json()
    draft = next(v for f in frameworks for v in f["versions"] if v["status"] == "draft")

    bad = client.patch(
        f"{API}/admin/versions/{draft['id']}/scoring", headers=admin,
        json={"formula": "make_it_up"},
    )
    assert bad.status_code == 422

    good = client.patch(
        f"{API}/admin/versions/{draft['id']}/scoring", headers=admin,
        json={"min_axis_coverage": 0.8, "na_handling": "zero"},
    )
    assert good.status_code == 200
    assert good.json()["scoring_config"]["min_axis_coverage"] == 0.8
    assert good.json()["scoring_config"]["na_handling"] == "zero"


def test_csv_content_import(client, admin):
    created = client.post(
        f"{API}/admin/frameworks", headers=admin,
        json={"code": "IMPORTTEST", "name_ar": "إطار الاستيراد", "name_en": "Import framework"},
    )
    assert created.status_code == 201
    version_id = created.json()["draft_version_id"]

    csv_text = (
        "axis_code,axis_name_ar,axis_name_en,axis_weight,question_code,text_ar,text_en,"
        "evidence_hint_ar,evidence_hint_en,weight,is_mandatory,evidence_required\n"
        "AX01,الحوكمة,Governance,1.5,AX01-Q1,سؤال أول,First question,ميثاق,Charter,1.2,yes,yes\n"
        "AX01,الحوكمة,Governance,1.5,AX01-Q2,سؤال ثانٍ,Second question,,,1.0,yes,no\n"
        "AX02,المخاطر,Risk,1.0,AX02-Q1,سؤال ثالث,Third question,سجل,Register,1.0,no,no\n"
        ",,,,,,,,,,,\n"
    )
    res = client.post(
        f"{API}/admin/versions/{version_id}/import",
        headers=admin,
        files={"file": ("content.csv", io.BytesIO(csv_text.encode("utf-8")), "text/csv")},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["axes_created"] == 2
    assert body["questions_created"] == 3

    detail = client.get(f"{API}/frameworks/versions/{version_id}", headers=admin).json()
    assert detail["axis_count"] == 2
    first = detail["axes"][0]["questions"][0]
    assert first["text_ar"] == "سؤال أول"
    assert first["text_en"] == "First question"
    assert first["weight"] == 1.2

    published = client.post(f"{API}/admin/versions/{version_id}/publish", headers=admin)
    assert published.status_code == 200
    assert published.json()["status"] == "published"


def test_admin_endpoints_reject_customers(client, owner):
    assert client.get(f"{API}/admin/frameworks", headers=owner).status_code == 403
    assert client.get(f"{API}/admin/organizations", headers=owner).status_code == 403
    assert client.get(f"{API}/admin/audit", headers=owner).status_code == 403


def test_audit_is_searchable_and_exportable(client, admin):
    found = client.get(f"{API}/admin/audit", headers=admin, params={"action": "user.login"})
    assert found.status_code == 200
    assert found.json()["count"] > 0
    assert all(i["action"] == "user.login" for i in found.json()["items"])

    export = client.get(f"{API}/admin/audit/export.csv", headers=admin)
    assert export.status_code == 200
    assert "timestamp,actor_email,action" in export.text


# ───────────────────────────── AI pipeline ─────────────────────────────────


def test_ai_pipeline_produces_traceable_findings(client, owner, reviewer):
    assessment_id, axes, _ = _complete_assessment(client, owner, "تقييم الذكاء الاصطناعي")

    run = client.post(
        f"{API}/assessments/{assessment_id}/ai/run", headers=owner, json={"stages": ["analyse"]}
    )
    assert run.status_code == 200, run.text
    assert run.json()["status"] == "completed"
    # With no API key configured the deterministic provider still produces output.
    assert run.json()["provider"] in ("rules", "anthropic")

    findings = client.get(
        f"{API}/assessments/{assessment_id}/ai/findings", headers=owner
    ).json()
    assert len(findings) >= len(axes) * 3
    assert {"strength", "gap", "opportunity"} <= {f["kind"] for f in findings}
    assert any(f["kind"] == "narrative" for f in findings)
    # AI-03: every finding carries its basis.
    assert all(f["citation"] for f in findings)
    assert all(f["review_status"] == "draft" for f in findings)


def test_reviewer_gate_over_ai_output(client, owner, reviewer):
    assessment_id, _, _ = _complete_assessment(client, owner, "تقييم بوابة المراجعة")
    client.post(
        f"{API}/assessments/{assessment_id}/ai/run", headers=owner, json={"stages": ["analyse"]}
    ).raise_for_status()
    finding = client.get(f"{API}/assessments/{assessment_id}/ai/findings", headers=owner).json()[0]

    # A customer cannot approve the AI's own output.
    assert client.patch(
        f"{API}/ai/findings/{finding['id']}", headers=owner, json={"review_status": "accepted"}
    ).status_code == 403

    edited = client.patch(
        f"{API}/ai/findings/{finding['id']}",
        headers=reviewer,
        json={"review_status": "edited", "body_ar": "نص عدّله المراجع.",
              "reviewer_note": "تم التحقق من الدليل"},
    )
    assert edited.status_code == 200
    assert edited.json()["review_status"] == "edited"
    assert edited.json()["body_ar"] == "نص عدّله المراجع."


def test_ai_never_changes_the_score(client, owner):
    assessment_id, _, _ = _complete_assessment(client, owner, "تقييم حتمية الاحتساب")
    before = client.get(f"{API}/assessments/{assessment_id}/results", headers=owner).json()
    client.post(
        f"{API}/assessments/{assessment_id}/ai/run", headers=owner,
        json={"stages": ["analyse", "recommend"]},
    ).raise_for_status()
    after = client.get(f"{API}/assessments/{assessment_id}/results", headers=owner).json()

    assert before["overall_score"] == after["overall_score"]
    assert before["maturity_level"] == after["maturity_level"]
    assert [a["score"] for a in before["axes"]] == [a["score"] for a in after["axes"]]


def test_document_extraction_and_evidence_review(client, owner):
    assessment_id, axes, questions = _complete_assessment(client, owner, "تقييم الأدلة")

    from openpyxl import Workbook

    wb = Workbook()
    sheet = wb.active
    sheet.append(["ميثاق الحوكمة المعتمد"])
    sheet.append(["يحدد صلاحيات مجلس الإدارة والإدارة التنفيذية"])
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    uploaded = client.post(
        f"{API}/documents",
        headers=owner,
        files={
            "file": (
                "governance.xlsx",
                buffer,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert uploaded.status_code == 201, uploaded.text
    document_id = uploaded.json()["id"]

    linked = client.post(
        f"{API}/assessments/{assessment_id}/evidence",
        headers=owner,
        json={"document_id": document_id, "question_ids": [questions[0]["id"]]},
    )
    assert linked.status_code == 201

    run = client.post(
        f"{API}/assessments/{assessment_id}/ai/run",
        headers=owner,
        json={"stages": ["extract", "relevance"]},
    )
    assert run.status_code == 200, run.text
    assert run.json()["summary"]["documents_extracted"] == 1

    coverage = client.get(
        f"{API}/assessments/{assessment_id}/ai/findings",
        headers=owner,
        params={"kind": "evidence_coverage"},
    ).json()
    assert len(coverage) == 1
    citation = coverage[0]["citation"]
    assert citation["document_id"] == document_id
    assert citation["filename"] == "governance.xlsx"
    assert citation["verdict"] in ("covered", "partial", "unclear", "missing")
    assert citation["language"] in ("ar", "en", "mixed", None)


# ─────────────────────── initiatives, roadmap, layers ──────────────────────


def test_roadmap_generation_and_reviewer_edits(client, owner, reviewer):
    assessment_id, _, _ = _complete_assessment(client, owner, "تقييم خارطة الطريق")
    client.post(
        f"{API}/assessments/{assessment_id}/ai/run", headers=owner, json={"stages": ["recommend"]}
    ).raise_for_status()

    roadmap = client.get(f"{API}/assessments/{assessment_id}/roadmap", headers=owner).json()
    assert roadmap["total"] > 0
    assert [h["code"] for h in roadmap["horizons"]] == ["immediate", "short", "medium", "long"]

    every = [i for h in roadmap["horizons"] for i in h["initiatives"]] + roadmap["unassigned"]
    # FR-28: each initiative traces to a gap and carries its delivery fields.
    assert all(i["linked_gap"] for i in every)
    assert all(i["title_ar"] and i["title_en"] for i in every)

    added = client.post(
        f"{API}/assessments/{assessment_id}/initiatives",
        headers=reviewer,
        json={"title_ar": "مبادرة المراجع", "title_en": "Reviewer initiative",
              "horizon_code": "short", "priority": 1},
    )
    assert added.status_code == 201
    assert added.json()["source"] == "reviewer"

    dropped = client.patch(
        f"{API}/initiatives/{every[0]['id']}", headers=reviewer,
        json={"is_included": False, "priority": 5},
    )
    assert dropped.status_code == 200
    assert dropped.json()["is_included"] is False

    # Re-running the engine must not wipe the reviewer's own initiative (FR-30).
    client.post(
        f"{API}/assessments/{assessment_id}/ai/run", headers=owner, json={"stages": ["recommend"]}
    ).raise_for_status()
    after = client.get(f"{API}/assessments/{assessment_id}/roadmap", headers=owner).json()
    survivors = [i for h in after["horizons"] for i in h["initiatives"]] + after["unassigned"]
    assert any(i["source"] == "reviewer" for i in survivors)


def test_layer_gating(client, owner):
    quick_id, _, _ = _complete_assessment(
        client, owner, "تقييم الطبقة الأولى", layer="quick_score"
    )
    blocked = client.get(f"{API}/assessments/{quick_id}/roadmap", headers=owner)
    assert blocked.status_code == 402
    assert blocked.json()["code"] == "layer.feature_not_included"

    assert client.get(f"{API}/assessments/{quick_id}/report.pdf", headers=owner).status_code == 402

    features = client.get(f"{API}/assessments/{quick_id}/layer-features", headers=owner).json()
    assert "scoring" in features["features"]
    assert "pdf_report" not in features["features"]


# ─────────────────────────────── reporting ─────────────────────────────────


def test_report_html_contains_every_required_section(client, owner):
    assessment_id, _, _ = _complete_assessment(client, owner, "تقييم التقرير")
    client.post(
        f"{API}/assessments/{assessment_id}/ai/run",
        headers=owner,
        json={"stages": ["analyse", "recommend"]},
    ).raise_for_status()

    res = client.get(f"{API}/assessments/{assessment_id}/report.html", headers=owner)
    assert res.status_code == 200
    html = res.text
    assert 'dir="rtl"' in html and 'lang="ar"' in html
    for section in (
        "الملخص التنفيذي",
        "نتائج النضج",
        "نتائج المحاور التفصيلية",
        "مجالات التحسين ذات الأولوية",
        "المبادرات والمشاريع الموصى بها",
        "خارطة طريق التنفيذ",
        "وثيقة سرّية",
    ):
        assert section in html, f"missing report section: {section}"
    assert "<svg" in html  # radar chart

    english = client.get(
        f"{API}/assessments/{assessment_id}/report.html", headers=owner, params={"locale": "en"}
    )
    assert 'dir="ltr"' in english.text
    assert "Executive summary" in english.text


def test_structured_export(client, owner):
    assessment_id, _, _ = _complete_assessment(client, owner, "تقييم التصدير")
    res = client.get(f"{API}/assessments/{assessment_id}/report.json", headers=owner)
    assert res.status_code == 200
    payload = res.json()
    assert payload["scoring"]["overall_score"] is not None
    assert payload["framework_version"]["scoring_config"]["formula"] == "weighted_average"
    assert payload["organisation"]["name_ar"]


def test_pdf_generation(client, owner):
    assessment_id, _, _ = _complete_assessment(client, owner, "تقييم PDF")
    res = client.get(f"{API}/assessments/{assessment_id}/report.pdf", headers=owner)
    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "application/pdf"
    assert res.content.startswith(b"%PDF")
    assert len(res.content) > 20_000  # a real multi-page document, not a stub


def test_release_gate_completes_the_assessment(client, owner, reviewer):
    assessment_id, _, _ = _complete_assessment(client, owner, "تقييم الإصدار")
    assert client.post(
        f"{API}/assessments/{assessment_id}/report/release", headers=owner, json={"locale": "ar"}
    ).status_code == 403

    released = client.post(
        f"{API}/assessments/{assessment_id}/report/release", headers=reviewer, json={"locale": "ar"}
    )
    assert released.status_code == 200
    assert released.json()["assessment_status"] == "completed"

    reports = client.get(f"{API}/assessments/{assessment_id}/reports", headers=owner).json()
    assert any(r["released"] for r in reports)


# ──────────────────────── remaining FR gaps ────────────────────────────────


def test_authorised_override_on_submit(client, owner, reviewer):
    framework = client.get(f"{API}/frameworks/current", headers=owner).json()
    axis = framework["axes"][5]
    created = client.post(
        f"{API}/assessments", headers=owner,
        json={"name": "تقييم التجاوز", "selected_axis_ids": [axis["id"]]},
    ).json()
    client.put(
        f"{API}/assessments/{created['id']}/responses",
        headers=owner,
        json=[{"question_id": axis["questions"][0]["id"], "score": 3}],
    ).raise_for_status()

    assert client.post(f"{API}/assessments/{created['id']}/submit", headers=owner).status_code == 409
    # A customer may not grant themselves the override.
    assert client.post(
        f"{API}/assessments/{created['id']}/submit",
        headers=owner,
        params={"override_incomplete": True},
    ).status_code == 403

    forced = client.post(
        f"{API}/assessments/{created['id']}/submit",
        headers=reviewer,
        params={"override_incomplete": True, "override_reason": "اتفاق مع العميل"},
    )
    assert forced.status_code == 200


def test_reviewer_view_reports_material_deltas(client, owner, reviewer):
    assessment_id, axes, questions = _complete_assessment(client, owner, "تقييم الفروق")
    target = next(q for q in questions if q["id"])
    # The customer answered on a 1..5 cycle; force a wide gap.
    client.post(
        f"{API}/assessments/{assessment_id}/questions/{target['id']}/override",
        headers=reviewer,
        json={"score": 5, "reason": "الدليل يدعم درجة أعلى"},
    ).raise_for_status()

    view = client.get(f"{API}/assessments/{assessment_id}/review", headers=reviewer)
    assert view.status_code == 200
    deltas = view.json()["score_deltas"]
    assert len(deltas) >= 1
    row = deltas[0]
    assert row["customer_score"] != row["reviewer_score"]
    assert row["reason"]
    assert client.get(f"{API}/assessments/{assessment_id}/review", headers=owner).status_code == 403


def test_question_filters(client, owner):
    framework = client.get(f"{API}/frameworks/current", headers=owner).json()
    axis = framework["axes"][6]
    created = client.post(
        f"{API}/assessments", headers=owner,
        json={"name": "تقييم الفلاتر", "selected_axis_ids": [axis["id"]]},
    ).json()
    client.put(
        f"{API}/assessments/{created['id']}/responses",
        headers=owner,
        json=[{"question_id": axis["questions"][0]["id"], "score": 2}],
    ).raise_for_status()

    base = f"{API}/assessments/{created['id']}/questions"
    everything = client.get(base, headers=owner).json()
    assert len(everything) == len(axis["questions"])

    answered = client.get(base, headers=owner, params={"answered": True}).json()
    assert len(answered) == 1

    unanswered = client.get(base, headers=owner, params={"answered": False}).json()
    assert len(unanswered) == len(axis["questions"]) - 1

    mandatory = client.get(base, headers=owner, params={"mandatory_only": True}).json()
    assert all(q["is_mandatory"] for q in mandatory)

    missing_evidence = client.get(base, headers=owner, params={"evidence_status": "missing"}).json()
    assert len(missing_evidence) == len(axis["questions"])

    # Substring search, so AX07-Q1 legitimately also matches AX07-Q10.
    code = axis["questions"][0]["code"]
    search = client.get(base, headers=owner, params={"q": code}).json()
    assert search and all(code in q["code"] for q in search)

    unique = client.get(base, headers=owner, params={"q": axis["questions"][4]["code"]}).json()
    assert len(unique) == 1


# ─────────────── administration portal: user register (FR-31) ───────────────


def test_user_register_lists_across_tenants(client, admin):
    res = client.get(f"{API}/admin/users?limit=500", headers=admin)
    assert res.status_code == 200, res.text
    body = res.json()
    emails = {row["email"] for row in body["items"]}
    # Both sides of the platform in one list — that is the point of the register.
    assert "admin@ivalueconsult.com" in emails
    assert "owner@demodeveloper.com" in emails
    assert "ivalue_admin" in body["roles"]
    owner_row = next(r for r in body["items"] if r["email"] == "owner@demodeveloper.com")
    assert owner_row["organization_name_ar"]


def test_user_register_filters(client, admin):
    res = client.get(f"{API}/admin/users?q=owner", headers=admin)
    assert res.status_code == 200
    assert all("owner" in r["email"] or "owner" in r["full_name"].lower()
               for r in res.json()["items"])

    res = client.get(f"{API}/admin/users?role=ivalue_admin", headers=admin)
    assert {r["role"] for r in res.json()["items"]} == {"ivalue_admin"}


def test_reviewer_may_read_but_not_write_the_register(client, reviewer, admin):
    assert client.get(f"{API}/admin/users", headers=reviewer).status_code == 200

    target = next(
        r for r in client.get(f"{API}/admin/users", headers=admin).json()["items"]
        if r["email"] == "owner@demodeveloper.com"
    )
    res = client.patch(
        f"{API}/admin/users/{target['id']}", json={"is_active": False}, headers=reviewer
    )
    assert res.status_code == 403


def test_suspend_and_restore_a_user(client, admin):
    users = client.get(f"{API}/admin/users", headers=admin).json()["items"]
    target = next(r for r in users if r["email"] == "owner@demodeveloper.com")

    assert client.patch(
        f"{API}/admin/users/{target['id']}", json={"is_active": False}, headers=admin
    ).json()["is_active"] is False
    # A suspended account cannot come back in through the front door.
    denied = client.post(
        f"{API}/auth/login", json={"email": target["email"], "password": PASSWORD}
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "auth.account_disabled"

    assert client.patch(
        f"{API}/admin/users/{target['id']}", json={"is_active": True}, headers=admin
    ).json()["is_active"] is True
    assert client.post(
        f"{API}/auth/login", json={"email": target["email"], "password": PASSWORD}
    ).status_code == 200


def test_admin_cannot_lock_itself_out(client, admin):
    me = client.get(f"{API}/auth/me", headers=admin).json()["user"]
    assert client.patch(
        f"{API}/admin/users/{me['id']}", json={"is_active": False}, headers=admin
    ).status_code == 409
    assert client.patch(
        f"{API}/admin/users/{me['id']}", json={"role": "viewer"}, headers=admin
    ).status_code == 409


def test_unknown_role_is_rejected(client, admin):
    users = client.get(f"{API}/admin/users", headers=admin).json()["items"]
    target = next(r for r in users if r["email"] == "owner@demodeveloper.com")
    res = client.patch(
        f"{API}/admin/users/{target['id']}", json={"role": "superuser"}, headers=admin
    )
    assert res.status_code == 422
    assert res.json()["code"] == "auth.unknown_role"


def test_horizons_can_be_read_before_they_are_rewritten(client, admin):
    """The editor screen needs a GET; the PUT replaces the whole set."""
    version = client.get(f"{API}/frameworks/current", headers=admin).json()
    res = client.get(f"{API}/admin/versions/{version['id']}/horizons", headers=admin)
    assert res.status_code == 200, res.text
    horizons = res.json()
    assert horizons and horizons == sorted(horizons, key=lambda h: h["order_index"])
    assert {"code", "name_ar", "name_en", "months_from", "months_to"} <= set(horizons[0])
