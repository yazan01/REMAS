"""Evidence bytes leave the API with headers that make a mislabelled file inert.

The threat this covers is specific. An evidence file is bytes a customer
uploaded, and `Document.content_type` beside it is whatever that customer's
browser *claimed* at upload time — the API never inspects the bytes to confirm
it. So a document can always be one kind of content wearing the label of
another, and the `preview` route serves it inline, on the API's own origin,
with the reviewer's session attached.

`X-Content-Type-Options: nosniff` is what keeps that from mattering: it forbids
the browser from second-guessing the declared type and executing HTML it found
inside a file labelled as an image.

These tests assert the header on the real HTTP responses rather than on the
handler source, so they keep holding if the handlers are rewritten.
"""

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
    from app import models  # noqa: F401

    Base.metadata.drop_all(bind=engine)
    init_db()
    with SessionLocal() as db:
        load_framework(db)
        seed_accounts(db)
        db.commit()
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="module")
def owner(client):
    res = client.post(
        f"{API}/auth/login",
        json={"email": "owner@demodeveloper.com", "password": "Remas#2026"},
    )
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture(scope="module")
def mislabelled_document(client, owner):
    """A document whose bytes are HTML and whose declared type is an image.

    This is exactly what the upload route accepts today: the type check reads
    the client's declaration, so the pairing is reachable by any authenticated
    user, not just by a modified client.
    """
    payload = b"<html><script>alert(document.cookie)</script></html>"
    res = client.post(
        f"{API}/documents",
        headers=owner,
        files={"file": ("evidence.png", payload, "image/png")},
    )
    assert res.status_code == 201, res.text
    return res.json()


@pytest.mark.parametrize("route", ["download", "preview"])
def test_evidence_is_served_with_nosniff(client, owner, mislabelled_document, route):
    """Without this header the browser may sniff the HTML and run it on our
    origin, which turns an evidence upload into stored XSS against a reviewer."""
    res = client.get(
        f"{API}/documents/{mislabelled_document['id']}/{route}", headers=owner
    )
    assert res.status_code == 200, res.text
    assert res.headers.get("x-content-type-options") == "nosniff", (
        f"the /{route} response served customer-supplied bytes without nosniff"
    )


def test_preview_serves_inline_and_download_serves_as_attachment(client, owner, mislabelled_document):
    """The disposition is the only thing that should differ between the two —
    pinned so a future refactor cannot quietly make `download` render in the
    browser instead of saving to disk."""
    preview = client.get(f"{API}/documents/{mislabelled_document['id']}/preview", headers=owner)
    download = client.get(f"{API}/documents/{mislabelled_document['id']}/download", headers=owner)
    assert preview.headers["content-disposition"].startswith("inline;")
    assert download.headers["content-disposition"].startswith("attachment;")


def test_declared_content_type_is_echoed_not_re_sniffed(client, owner, mislabelled_document):
    """Paired with nosniff, echoing the declared type is safe: the browser is
    now bound to it. Asserted so the pairing stays intentional — echoing the
    type *without* nosniff is the combination that is dangerous."""
    res = client.get(f"{API}/documents/{mislabelled_document['id']}/preview", headers=owner)
    assert res.headers["content-type"].startswith("image/png")
