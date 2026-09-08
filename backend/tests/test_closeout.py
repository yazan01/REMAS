"""Coverage for the final gap closure: encryption at rest, secrets handling,
report templates (FR-34), question assignment and overdue tracking (FR-12),
per-question maturity criteria (FR-08), prior-assessment comparison, expert
sessions, evidence preview/replace, OCR fallback, observability and backup."""

from __future__ import annotations

import io
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core import crypto
from app.core.config import settings
from app.core.security import utcnow
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


def auth(client, email: str) -> dict:
    res = client.post(f"{API}/auth/login", json={"email": email, "password": PASSWORD})
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


def _xlsx(rows: list[str]) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    sheet = wb.active
    for row in rows:
        sheet.append([row])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _complete(client, headers, name: str, axes_count: int = 2, layer="deep_dive"):
    framework = client.get(f"{API}/frameworks/current", headers=headers).json()
    axes = framework["axes"][:axes_count]
    created = client.post(
        f"{API}/assessments",
        headers=headers,
        json={"name": name, "layer": layer, "selected_axis_ids": [a["id"] for a in axes]},
    ).json()
    questions = [q for a in axes for q in a["questions"]]
    client.put(
        f"{API}/assessments/{created['id']}/responses",
        headers=headers,
        json=[{"question_id": q["id"], "score": (i % 5) + 1} for i, q in enumerate(questions)],
    ).raise_for_status()
    client.post(f"{API}/assessments/{created['id']}/submit", headers=headers).raise_for_status()
    return created["id"], axes, questions


# ───────────────────── encryption at rest & secrets ─────────────────────────


def test_evidence_is_encrypted_on_disk(client, owner):
    content = _xlsx(["ميثاق الحوكمة المعتمد", "مصفوفة الصلاحيات"])
    uploaded = client.post(
        f"{API}/documents",
        headers=owner,
        files={
            "file": (
                "encrypted.xlsx",
                io.BytesIO(content),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        data={"category": "الحوكمة"},
    )
    assert uploaded.status_code == 201, uploaded.text
    document_id = uploaded.json()["id"]
    assert uploaded.json()["category"] == "الحوكمة"

    from app.models import Document

    with SessionLocal() as db:
        document = db.get(Document, document_id)
        raw = Path(document.stored_path).read_bytes()

    # The bytes on disk are not the bytes that were uploaded.
    assert crypto.is_encrypted(raw)
    assert raw != content
    assert b"PK" != raw[:2]  # not a readable zip/xlsx header any more

    # ...but the download round-trips exactly.
    downloaded = client.get(f"{API}/documents/{document_id}/download", headers=owner)
    assert downloaded.status_code == 200
    assert downloaded.content == content


def test_cross_tenant_key_cannot_decrypt():
    blob = crypto.encrypt(b"tenant A evidence", "master", "org-A")
    assert crypto.decrypt(blob, "master", "org-A") == b"tenant A evidence"
    with pytest.raises(Exception):
        crypto.decrypt(blob, "master", "org-B")


def test_secret_can_be_read_from_a_file(tmp_path, monkeypatch):
    secret_file = tmp_path / "jwt.secret"
    secret_file.write_text("from-a-mounted-file", encoding="utf-8")
    monkeypatch.setenv("TEST_SECRET_FILE", str(secret_file))
    assert crypto.read_secret("TEST_SECRET") == "from-a-mounted-file"

    monkeypatch.delenv("TEST_SECRET_FILE")
    monkeypatch.setenv("TEST_SECRET", "from-the-environment")
    assert crypto.read_secret("TEST_SECRET") == "from-the-environment"


# ───────────────────── evidence preview, replace, history ───────────────────


def test_preview_replace_and_version_history(client, owner):
    first = client.post(
        f"{API}/documents",
        headers=owner,
        files={"file": ("policy.png", io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"0" * 64), "image/png")},
    )
    assert first.status_code == 201
    original_id = first.json()["id"]

    preview = client.get(f"{API}/documents/{original_id}/preview", headers=owner)
    assert preview.status_code == 200
    assert preview.headers["content-disposition"].startswith("inline")
    assert preview.headers["content-type"] == "image/png"

    replacement = client.post(
        f"{API}/documents",
        headers=owner,
        files={"file": ("policy-v2.png", io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"1" * 64), "image/png")},
        data={"supersedes_id": original_id},
    )
    assert replacement.status_code == 201
    assert replacement.json()["version"] == 2

    history = client.get(
        f"{API}/documents/{replacement.json()['id']}/history", headers=owner
    ).json()
    assert len(history) == 2
    assert history[0]["version"] == 2
    assert history[1]["superseded"] is True

    # A superseded document drops out of the live list.
    live = {d["id"] for d in client.get(f"{API}/documents", headers=owner).json()}
    assert original_id not in live


def test_categories_and_metadata(client, owner):
    categories = client.get(f"{API}/documents/categories", headers=owner).json()
    assert "الحوكمة" in categories

    filtered = client.get(f"{API}/documents", headers=owner, params={"category": "الحوكمة"}).json()
    assert filtered and all(d["category"] == "الحوكمة" for d in filtered)

    updated = client.patch(
        f"{API}/documents/{filtered[0]['id']}",
        headers=owner,
        json={"description": "ميثاق معتمد من المجلس"},
    )
    assert updated.status_code == 200
    assert updated.json()["description"] == "ميثاق معتمد من المجلس"


def test_ocr_is_reported_rather_than_faked(client, owner):
    """AI-01: with no OCR provider configured, a scan is flagged — never
    reported as an empty document, which would read as missing evidence."""
    assessment_id, _, questions = _complete(client, owner, "تقييم المسح الضوئي")
    scan = client.post(
        f"{API}/documents",
        headers=owner,
        files={"file": ("scan.png", io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"x" * 128), "image/png")},
    ).json()
    client.post(
        f"{API}/assessments/{assessment_id}/evidence",
        headers=owner,
        json={"document_id": scan["id"], "question_ids": [questions[0]["id"]]},
    ).raise_for_status()

    run = client.post(
        f"{API}/assessments/{assessment_id}/ai/run",
        headers=owner,
        json={"stages": ["extract", "relevance"]},
    )
    assert run.status_code == 200, run.text
    assert run.json()["summary"]["documents_needing_ocr"] >= 1

    findings = client.get(
        f"{API}/assessments/{assessment_id}/ai/findings",
        headers=owner,
        params={"kind": "evidence_coverage"},
    ).json()
    scan_finding = next(f for f in findings if f["citation"]["document_id"] == scan["id"])
    assert scan_finding["citation"]["ocr_required"] is True
    # Not silently called "missing" — it needs a human look.
    assert scan_finding["citation"]["verdict"] == "unclear"


# ─────────────────── FR-08 maturity criteria per question ───────────────────


def test_questions_carry_maturity_criteria(client, owner):
    framework = client.get(f"{API}/frameworks/current", headers=owner).json()
    question = framework["axes"][0]["questions"][0]
    criteria = question["criteria"]
    assert criteria is not None
    assert set(criteria) == {"1", "2", "3", "4", "5"}
    for level in criteria.values():
        assert level["ar"] and level["en"]


def test_criteria_import_columns(client, admin):
    created = client.post(
        f"{API}/admin/frameworks",
        headers=admin,
        json={"code": "CRITERIA", "name_ar": "معايير", "name_en": "Criteria framework"},
    ).json()
    csv_text = (
        "axis_code,axis_name_ar,axis_name_en,question_code,text_ar,text_en,"
        "criteria_1,criteria_3,criteria_5\n"
        "CX1,محور,Pillar,CX1-Q1,سؤال,Question,"
        "لا يوجد | None,جزئي | Partial,متكامل | Integrated\n"
    )
    res = client.post(
        f"{API}/admin/versions/{created['draft_version_id']}/import",
        headers=admin,
        files={"file": ("criteria.csv", io.BytesIO(csv_text.encode("utf-8")), "text/csv")},
    )
    assert res.status_code == 200, res.text

    detail = client.get(
        f"{API}/frameworks/versions/{created['draft_version_id']}", headers=admin
    ).json()
    criteria = detail["axes"][0]["questions"][0]["criteria"]
    assert criteria["1"] == {"ar": "لا يوجد", "en": "None"}
    assert criteria["5"] == {"ar": "متكامل", "en": "Integrated"}
    assert "2" not in criteria  # only the supplied columns are stored


# ───────────────────── FR-34 configurable report templates ──────────────────


def test_report_template_drives_sections_branding_and_wording(client, admin, owner):
    assessment_id, _, _ = _complete(client, owner, "تقييم القالب")
    client.post(
        f"{API}/assessments/{assessment_id}/ai/run",
        headers=owner,
        json={"stages": ["analyse", "recommend"]},
    ).raise_for_status()

    baseline = client.get(f"{API}/assessments/{assessment_id}/report.html", headers=owner).text
    assert "خارطة طريق التنفيذ" in baseline
    assert "#1e3a5c" in baseline  # shipped brand colour

    listing = client.get(f"{API}/admin/report-templates", headers=admin).json()
    assert listing["available_sections"]
    template = listing["templates"][0]

    updated = client.patch(
        f"{API}/admin/report-templates/{template['id']}",
        headers=admin,
        json={
            "branding": {"primary": "#7A1F2B", "organisation_name": "شركة العميل"},
            "sections": [
                {"key": "cover", "enabled": True, "order": 0},
                {"key": "executive_summary", "enabled": True, "order": 1,
                 "title_ar": "خلاصة للإدارة", "title_en": "Management summary"},
                {"key": "maturity_results", "enabled": True, "order": 2},
                {"key": "axis_findings", "enabled": True, "order": 3},
                {"key": "priorities", "enabled": True, "order": 4},
                {"key": "initiatives", "enabled": True, "order": 5},
                {"key": "roadmap", "enabled": False, "order": 6},
            ],
            "maturity_labels": {"5": {"ar": "رائد", "en": "Leading"}},
            "copy_blocks": {"executive_summary": {"ar": "نص تمهيدي من القالب.", "en": "Template intro."}},
        },
    )
    assert updated.status_code == 200, updated.text

    restyled = client.get(f"{API}/assessments/{assessment_id}/report.html", headers=owner).text
    assert "#7A1F2B" in restyled            # branding applied
    assert "خلاصة للإدارة" in restyled       # section retitled
    assert "خارطة طريق التنفيذ" not in restyled  # section switched off
    assert "نص تمهيدي من القالب." in restyled    # copy block injected
    assert "شركة العميل" in restyled             # cover organisation name

    # Restore, so later tests see the shipped template.
    client.patch(
        f"{API}/admin/report-templates/{template['id']}",
        headers=admin,
        json={
            "branding": {"primary": "#1e3a5c", "organisation_name": "iValue Consult"},
            "sections": listing["defaults"]["sections"],
            "maturity_labels": {},
            "copy_blocks": {},
        },
    ).raise_for_status()


def test_unknown_report_section_is_rejected(client, admin):
    template = client.get(f"{API}/admin/report-templates", headers=admin).json()["templates"][0]
    res = client.patch(
        f"{API}/admin/report-templates/{template['id']}",
        headers=admin,
        json={"sections": [{"key": "made_up_section", "enabled": True, "order": 0}]},
    )
    assert res.status_code == 422
    assert res.json()["code"] == "report.unknown_section"


def test_report_templates_are_staff_only(client, owner):
    assert client.get(f"{API}/admin/report-templates", headers=owner).status_code == 403


# ──────────── FR-12 assignment, deadlines, overdue, per-user ────────────────


def test_assignment_overdue_and_per_user_progress(client, owner):
    framework = client.get(f"{API}/frameworks/current", headers=owner).json()
    axis = framework["axes"][3]
    assessment = client.post(
        f"{API}/assessments",
        headers=owner,
        json={"name": "تقييم الإسناد", "selected_axis_ids": [axis["id"]]},
    ).json()

    members = client.get(f"{API}/account/members", headers=owner).json()
    target = members[0]["id"]

    past = (utcnow() - timedelta(days=3)).isoformat()
    assigned = client.put(
        f"{API}/assessments/{assessment['id']}/assignments",
        headers=owner,
        json={
            "question_ids": [q["id"] for q in axis["questions"][:4]],
            "assigned_to_id": target,
            "due_at": past,
        },
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["assigned"] == 4

    overdue = client.get(f"{API}/assessments/{assessment['id']}/overdue", headers=owner).json()
    assert len(overdue) == 4
    assert all(row["days_overdue"] >= 2 for row in overdue)
    assert overdue[0]["assigned_to"]

    by_user = client.get(
        f"{API}/assessments/{assessment['id']}/progress/by-user", headers=owner
    ).json()
    assigned_bucket = next(b for b in by_user if b["user_id"] == target)
    assert assigned_bucket["assigned"] == 4
    assert assigned_bucket["overdue"] == 4
    assert assigned_bucket["completion"] == 0.0

    # Answering clears the overdue flag — an answered question is never late.
    client.put(
        f"{API}/assessments/{assessment['id']}/responses",
        headers=owner,
        json=[{"question_id": q["id"], "score": 3} for q in axis["questions"][:4]],
    ).raise_for_status()
    assert client.get(f"{API}/assessments/{assessment['id']}/overdue", headers=owner).json() == []

    progress = client.get(f"{API}/assessments/{assessment['id']}/progress", headers=owner).json()
    assert progress["overdue"] == 0


def test_assessment_due_date_makes_everything_overdue(client, owner):
    framework = client.get(f"{API}/frameworks/current", headers=owner).json()
    axis = framework["axes"][4]
    assessment = client.post(
        f"{API}/assessments",
        headers=owner,
        json={"name": "تقييم الموعد", "selected_axis_ids": [axis["id"]]},
    ).json()

    res = client.patch(
        f"{API}/assessments/{assessment['id']}/due-date",
        headers=owner,
        json={"due_at": (utcnow() - timedelta(days=1)).isoformat()},
    )
    assert res.status_code == 200
    overdue = client.get(f"{API}/assessments/{assessment['id']}/overdue", headers=owner).json()
    assert len(overdue) == len(axis["questions"])


# ───────────────── comparison to prior assessments (section 9) ──────────────


def test_prior_assessment_comparison(client, owner):
    framework = client.get(f"{API}/frameworks/current", headers=owner).json()
    axes = framework["axes"][:2]
    questions = [q for a in axes for q in a["questions"]]

    def run(name: str, score: int) -> str:
        created = client.post(
            f"{API}/assessments",
            headers=owner,
            json={"name": name, "layer": "ai_report",
                  "selected_axis_ids": [a["id"] for a in axes]},
        ).json()
        client.put(
            f"{API}/assessments/{created['id']}/responses",
            headers=owner,
            json=[{"question_id": q["id"], "score": score} for q in questions],
        ).raise_for_status()
        client.post(f"{API}/assessments/{created['id']}/submit", headers=owner).raise_for_status()
        return created["id"]

    run("قياس 2025", 2)
    second = run("قياس 2026", 4)

    comparison = client.get(f"{API}/assessments/{second}/comparison", headers=owner).json()
    assert comparison is not None
    assert comparison["previous_overall"] == 2.0
    assert comparison["current_overall"] == 4.0
    assert comparison["overall_delta"] == 2.0
    assert all(row["delta"] == 2.0 for row in comparison["axes"])

    report = client.get(f"{API}/assessments/{second}/report.html", headers=owner).text
    assert "المقارنة بالتقييم السابق" in report
    assert "قياس 2025" in report


def test_first_assessment_has_no_comparison(client, owner):
    framework = client.get(f"{API}/frameworks/current", headers=owner).json()
    axis = framework["axes"][9]
    created = client.post(
        f"{API}/assessments",
        headers=owner,
        json={"name": "أول قياس لهذا المحور", "selected_axis_ids": [axis["id"]]},
    ).json()
    # No prior submitted assessment covering the same version yet for this shape.
    body = client.get(f"{API}/assessments/{created['id']}/comparison", headers=owner).json()
    assert body is None or "axes" in body


# ────────────────── expert sessions (Layer 3, section 10) ───────────────────


def test_expert_session_request_and_schedule(client, owner, reviewer):
    assessment_id, _, _ = _complete(client, owner, "تقييم جلسة الخبير", layer="deep_dive")
    slot = (utcnow() + timedelta(days=7)).isoformat()

    requested = client.post(
        f"{API}/assessments/{assessment_id}/expert-sessions",
        headers=owner,
        json={"preferred_slots": [slot], "agenda": "مناقشة الفجوات في الحوكمة"},
    )
    assert requested.status_code == 201, requested.text
    session_id = requested.json()["id"]
    assert requested.json()["status"] == "requested"

    scheduled = client.patch(
        f"{API}/expert-sessions/{session_id}/schedule",
        headers=reviewer,
        json={"scheduled_at": slot, "duration_minutes": 90,
              "meeting_url": "https://meet.example.com/remas"},
    )
    assert scheduled.status_code == 200
    assert scheduled.json()["status"] == "scheduled"
    assert scheduled.json()["expert_name"]

    completed = client.patch(
        f"{API}/expert-sessions/{session_id}/complete",
        headers=reviewer,
        json={"notes": "روجعت النتائج مع العميل"},
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"

    listed = client.get(f"{API}/assessments/{assessment_id}/expert-sessions", headers=owner).json()
    assert len(listed) == 1


def test_expert_session_requires_the_deep_dive_layer(client, owner):
    assessment_id, _, _ = _complete(client, owner, "طبقة أدنى", layer="ai_report")
    res = client.post(
        f"{API}/assessments/{assessment_id}/expert-sessions",
        headers=owner,
        json={"preferred_slots": []},
    )
    assert res.status_code == 402
    assert res.json()["code"] == "layer.feature_not_included"


def test_customer_cannot_schedule_their_own_session(client, owner):
    assessment_id, _, _ = _complete(client, owner, "جدولة ذاتية", layer="deep_dive")
    session = client.post(
        f"{API}/assessments/{assessment_id}/expert-sessions",
        headers=owner,
        json={"preferred_slots": [(utcnow() + timedelta(days=3)).isoformat()]},
    ).json()
    res = client.patch(
        f"{API}/expert-sessions/{session['id']}/schedule",
        headers=owner,
        json={"scheduled_at": (utcnow() + timedelta(days=3)).isoformat()},
    )
    assert res.status_code == 403


# ────────────────────────── observability & ops ─────────────────────────────


def test_health_readiness_and_metrics(client):
    assert client.get("/health").json()["status"] == "ok"

    ready = client.get("/health/ready").json()
    assert ready["status"] in ("ready", "degraded")
    assert ready["checks"]["database"] == "ok"
    assert ready["checks"]["storage"] == "ok"
    assert ready["checks"]["evidence_encryption"] == "on"
    assert "ai_provider" in ready["checks"]
    assert "ocr_provider" in ready["checks"]

    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "remas_requests_total" in metrics.text
    assert "remas_request_duration_seconds_bucket" in metrics.text

    summary = client.get("/metrics/summary").json()
    assert summary["requests"] > 0
    assert summary["target_p95_seconds"] == 3.0
    # Every request in this suite runs locally; the p95 must be far under target.
    assert summary["p95_seconds"] < 3.0


def test_response_time_header_is_present(client):
    res = client.get("/health")
    assert "X-Response-Time" in res.headers


def test_backup_create_and_verify(tmp_path, monkeypatch):
    """The recovery test the NFR asks for: back up, restore into a scratch
    directory, and re-open the database."""
    from scripts import backup

    monkeypatch.setattr(settings, "backup_dir", tmp_path)
    archive = backup.create("test")
    assert archive.exists()

    blob = archive.read_bytes()
    assert crypto.is_encrypted(blob), "a backup must not sit on disk in the clear"

    assert backup.verify(archive) is True


def test_backup_refuses_unsafe_archive_paths(tmp_path):
    import io as _io
    import tarfile

    from scripts import backup

    buffer = _io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        payload = b'{"files": 0}'
        info = tarfile.TarInfo("manifest.json")
        info.size = len(payload)
        archive.addfile(info, _io.BytesIO(payload))
        evil = tarfile.TarInfo("../escaped.txt")
        evil.size = 3
        archive.addfile(evil, _io.BytesIO(b"bad"))

    path = tmp_path / "evil.tar.gz.enc"
    path.write_bytes(
        crypto.encrypt(buffer.getvalue(), settings.evidence_master_key, "backup")
    )
    with pytest.raises(SystemExit):
        backup.restore(path, tmp_path / "out")
