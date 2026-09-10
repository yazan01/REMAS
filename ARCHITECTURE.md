# REMAS — Architecture

How the system is built, why it is built that way, and which rules are enforced
by tests rather than by good intentions.

This document describes the architecture **as implemented**. Where something is
a known gap, it says so.

---

## 1. What the system is

A multi-tenant maturity-assessment platform for real-estate developers. A
customer organisation answers a weighted questionnaire, attaches evidence
documents, and receives a scored, bilingual (Arabic/English) report. iValue
staff review the answers, run an AI analysis over the evidence, and release the
final PDF.

Two processes:

| | Stack | Entry point |
| --- | --- | --- |
| Backend | Python · FastAPI · SQLAlchemy · SQLite (PostgreSQL by config) | `backend/app/main.py` |
| Frontend | Next.js 15 · TypeScript · CSS custom properties | `frontend/src/app/` |

---

## 2. Request flow

```
Browser
   ↓  fetch, through one client module (frontend/src/lib/api.ts)
HTTP  /api/v1/...
   ↓
Middleware        CORS · MetricsMiddleware (records p50/p95/p99)
   ↓
Dependencies      get_current_user   → JWT decode, user lookup
                  get_assessment     → tenant isolation gate
                  require_ivalue     → role gate
                  require_submitted  → lifecycle gate
   ↓
Controller        app/api/routes/**    validates input, holds no business rules
   ↓
Service           app/services/**      the rules and the orchestration
   ↓
Model / Session   app/models, app/db   SQLAlchemy
   ↓
Database
```

Errors take one path out: `APIError` → `api_error_handler`, which returns a
code plus `message_ar` and `message_en`. The client renders whichever language
is active without another round trip.

---

## 3. Layering, and how it is enforced

```
main  →  api (+ schemas)  →  services  →  models / db  →  core
```

`core` is shared by everything on purpose — configuration, error codes and
crypto have no dependencies of their own.

These are not conventions in a document. `tests/test_architecture.py` parses
the real import graph and fails the build on:

| Rule | What it prevents |
| --- | --- |
| No layer inversion | The AI pipeline importing an HTTP controller to read a file — which once made the analysis engine unusable outside a web request |
| No route imports another route | A controller borrowing another's helper instead of moving it down a layer |
| No import cycles | Including cycles hidden by deferring an import into a function body |
| Scoring imports no framework | `services/scoring.py` must stay pure: FR-26 requires it deterministic and testable |
| No module past a reviewable size | 560 lines for controllers, 600 for services |

Two further gates:

- **`tests/test_api_contract.py`** — the public URL surface is recorded in
  `tests/api_contract.txt` (109 method+path pairs). Moving code between modules
  must leave it byte-identical. Changing it is a deliberate act:
  `python -m scripts.api_contract --write`, and the diff is reviewed as the
  API-change section of the pull request.
- **`tests/test_static_analysis.py`** — undefined names and unexplained unused
  imports fail the build.

---

## 4. Module map

### Backend

```
backend/app/
├── main.py            FastAPI app, health, readiness, metrics
├── api/
│   ├── deps.py        request gates: auth, tenancy, role, lifecycle
│   ├── router.py      mounts every route package under /api/v1
│   └── routes/
│       ├── auth.py            register, verify, login, me
│       ├── account/           passwords · mfa · team          (FR-03, FR-04)
│       ├── catalogue.py       service layers and pillars      (FR-01)
│       ├── organizations.py   workspace and developer profile (FR-02)
│       ├── frameworks.py      published framework content, read-only
│       ├── assessments.py     the assessment lifecycle        (FR-05 → FR-26)
│       ├── evidence.py        upload, link, preview, versions (FR-14 → FR-19)
│       ├── insights/          ai · initiatives · reports · features
│       ├── governance/        assignments · expert_sessions   (FR-12, §10)
│       └── admin/             the administration portal       (FR-31 → FR-35)
├── services/
│   ├── scoring.py             pure functions — the calculation engine
│   ├── assessment_service.py  ORM bridge over scoring
│   ├── entitlements.py        which features a service layer unlocks
│   ├── evidence_store.py      tenant-scoped storage + encryption envelope
│   ├── reporting/             context · renderer · styles · fonts · pdf · export
│   ├── ai/                    extraction · ocr · provider · pipeline
│   ├── audit.py               the audit trail
│   ├── framework_service.py   version resolution
│   ├── content_import.py      Excel/CSV bulk load
│   └── settings_store.py      encrypted settings (AI keys)
├── models/            SQLAlchemy entities
├── schemas/           request/response contracts
├── db/                engine, session, seed + seed content
└── core/              config, security, crypto, errors, observability
```

Each route package exposes one `router` from its `__init__.py`; the modules
inside it are internal. `admin/` and `account/` carry their URL prefix on the
package router, so the modules inside spell only their own segment.
`insights/` and `governance/` carry no prefix, because their routes hang off
several different roots — so those modules spell full paths.

### Frontend

```
frontend/src/
├── app/          one directory per route (Next.js App Router)
├── components/   header, language toggle, radar, document preview
├── lib/
│   ├── api.ts    the only place fetch() is called
│   └── session.tsx
├── i18n/         message dictionary + locale/direction provider
└── theme/
    └── palette.ts   the only place a colour is written
```

Two single-source rules hold, and both are greppable:

- No component calls `fetch` directly — everything goes through `lib/api.ts`,
  which owns the base URL, the bearer token and error normalisation.
- No colour literal exists outside `theme/palette.ts`.

---

## 5. Where the business rules live

**In `services/scoring.py`, and nowhere else.** It is pure: no FastAPI, no
SQLAlchemy, no `app.models`, no environment access. A test enforces that,
because FR-26 requires the calculation to be deterministic and reproducible.

The rules it owns:

- Weighted average, `Σ(score × weight) ÷ Σ(weights)`, keeping results on the
  1–5 scale. The BRD's literal formula divides by question count, which leaves
  the scale whenever weights differ; it remains available as
  `formula: "brd_literal"` and emits a warning.
- "Not applicable" is neutral — excluded from numerator and denominator.
- An axis answered below the coverage floor (default 60%) is excluded from the
  overall score, with the reason surfaced in the results.

**The AI never scores.** It extracts, compares, explains and recommends; every
output lands as a proposal behind a human review gate. The numbers come from
the scoring engine whichever provider produced the prose.

---

## 6. Security architecture

| Concern | Implementation |
| --- | --- |
| Authentication | Bearer JWT (HS256), bcrypt password hashes, optional TOTP MFA |
| Authorisation | Role gates in `api/deps.py`; iValue roles cross tenants, customers do not |
| Tenant isolation | `get_assessment` returns **404, not 403**, for another tenant's record — the API never confirms that it exists |
| Encryption at rest | Evidence sealed with AES-256-GCM under a **per-tenant** key derived by HKDF, so a raw disk or backup copy does not cross the tenant boundary |
| Secrets | Read from an environment variable or from `<NAME>_FILE` (the Docker/Kubernetes convention). Outside development the app **refuses to start** on the placeholder JWT secret, or on one under 32 bytes |
| Path traversal | Stored evidence filenames are the SHA-256 of the content — a caller cannot smuggle `../` through a hex digest |
| Uploaded content | Served with `X-Content-Type-Options: nosniff`. The declared content type is the client's claim, not a fact about the bytes, so the browser is bound to it rather than free to sniff HTML out of a file labelled as an image |
| Credential logging | Single-use reset and invitation tokens are logged **in development only**; production records the event without the value |

---

## 7. External boundaries

Every outbound dependency is reached through one module, so it can be replaced
by configuration rather than by a code change:

| Provider | Module | Fallback |
| --- | --- | --- |
| AI analysis | `services/ai/provider.py` | A deterministic provider that needs no network and no key |
| OCR | `services/ai/ocr.py` | Tesseract locally, Azure Document Intelligence by config, `ocr_required` when neither is available |
| PDF printing | `services/reporting/pdf.py` | None — headless Chromium is required |

**The report reaches no network at all.** Its typefaces are bundled and inlined
as data URIs (`services/reporting/fonts.py`). This is not cosmetic. The report
previously linked Google Fonts while the printer waited for `networkidle`, so
on a network that drops egress rather than refusing it, the PDF stalled for 30
seconds and then failed — and `release_report` calls the printer unguarded.

---

## 8. Data and migrations

SQLAlchemy models, created with `Base.metadata.create_all` at startup.

**There is no migration tool.** This is the significant known gap. It is
adequate while the schema is additive and the deployment is new; it is not
adequate for a production schema change against existing customer data.
Adopting Alembic is the recommended next step.

Framework *content* is versioned inside the database instead: a published
version is immutable, and editing means cloning it to a draft and publishing
that. Historical assessments therefore stay reproducible (FR-35).

---

## 9. Observability

| Endpoint | Purpose |
| --- | --- |
| `/health` | Liveness. Deliberately does no I/O, so a slow database never takes the container down |
| `/health/ready` | Readiness: database, storage, evidence encryption, AI and OCR provider, report fonts |
| `/metrics` | Prometheus exposition |
| `/metrics/summary` | p50/p95/p99 against the 3-second NFR |

---

## 10. How to add things

**An endpoint in an existing domain** — add it to the right module under
`api/routes/`, put the rule in a service, then run
`python -m scripts.api_contract --write` and review the one-line diff.

**A new domain** — create a package under `api/routes/` exposing a `router`
from its `__init__.py`, mount it in `api/router.py`, and record the new routes
in the contract. Nothing else needs to change.

**A new external provider** — add an adapter module beside the existing one and
select it by configuration. Do not call an SDK from a controller, or from a
service that owns business rules.

**A schema change** — read section 8 first. There is no migration tool yet.
