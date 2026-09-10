# Contributing to REMAS

Read [ARCHITECTURE.md](ARCHITECTURE.md) first. It explains where things live
and why, which is most of what you need to make a change in the right place.

---

## Getting set up

```bash
# backend
cd backend
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt   # macOS / Linux

./.venv/Scripts/python.exe -m playwright install chromium        # once, for PDF
./.venv/Scripts/python.exe -m app.db.seed --reset                # content + demo accounts
./.venv/Scripts/python.exe -m uvicorn app.main:app --port 8010 --reload

# frontend
cd frontend
npm install
npm run dev
```

Backend on `127.0.0.1:8010`, frontend on `localhost:3000`, interactive API docs
at `/docs`.

---

## Before you open a pull request

```bash
cd backend
./.venv/Scripts/python.exe -m pytest -q                # the whole suite
./.venv/Scripts/python.exe -m scripts.api_contract     # expect: "no drift"
./.venv/Scripts/python.exe -m pip_audit                # dependency CVEs

cd ../frontend
npm run build                                          # full type check
```

`npm run build` writes to `.next-build`, not `.next`, deliberately: the two
used to share a directory, so a build would rewrite chunks the dev server was
still serving and the page died with `Cannot find module './960.js'`. You can
build at any time without dropping a running server.

---

## The rules the build enforces

You do not have to remember these — a test will tell you. It is quicker if you
know them going in.

### Layering

```
main  →  api (+ schemas)  →  services  →  models / db  →  core
```

Nothing may depend outward. A controller must not import another controller: if
one needs another's helper, that helper is a service in the wrong place — move
it down a layer rather than sideways. Deferring an import into a function body
does not get you past this; the check reads those too.

### `services/scoring.py` stays pure

No FastAPI, no SQLAlchemy, no `app.models`, no configuration reads. FR-26
requires the calculation to be deterministic and reproducible, and it is the
one module in the system where a hidden dependency would cost the most.

### The URL surface is a contract

`tests/api_contract.txt` records all 109 method+path pairs. Refactoring must
leave it byte-identical. When you genuinely intend an API change:

```bash
python -m scripts.api_contract --write
```

and treat the resulting diff as the API-change section of your pull request.
This exists because a controller split is the change most likely to move a URL
by accident — a router picks up a prefix it did not have, every handler still
works, every other test still passes, and every deployed client breaks.

### Module size

560 lines for a controller, 600 for a service. Generous on purpose: the limit
exists to catch a module quietly taking on a second responsibility, not to
enforce a style. If you are near it, the question is whether there are two
things in the file — not how to save lines.

### No undefined names, no unexplained dead imports

`tests/test_static_analysis.py` runs pyflakes. An import that exists for its
side effect is fine, but say so on the line:

```python
from app import models  # noqa: F401  (registers mappers)
```

This gate is not bureaucracy. It caught a real report-rendering bug that five
rounds of human review had missed.

---

## Writing a change

**Put the rule in a service, not in a controller.** A controller validates
input, calls one service, and shapes the response. If you find yourself writing
`if` over business state in a route, it belongs a layer down.

**Both languages, always.** Every content row carries `_ar` and `_en`, and
every response returns both so the client can switch language without a round
trip. That includes error messages: `message_ar` and `message_en`. Never
translate content in the frontend.

**Layout uses logical CSS properties.** `margin-inline-start`, not
`margin-left`. RTL and LTR then work from one stylesheet.

**Colours go in `frontend/src/theme/palette.ts`.** Nowhere else. To check:

```bash
cd frontend
grep -rInE '#[0-9a-fA-F]{3,8}|rgba?\(' src --include='*.tsx' --include='*.css' \
  | grep -v 'src/theme/palette.ts' | grep -v color-mix
# no output = the rule holds
```

**Network calls go through `frontend/src/lib/api.ts`.** It owns the base URL,
the bearer token, and error normalisation.

---

## Tests

Write the test that would have caught the bug. Concretely, that means:

- **Assert on behaviour, not on source text** where you can. A test that greps
  a handler stops holding the moment the handler is rewritten; a test that
  checks the HTTP response keeps holding.
- **Verify the test fails without the fix.** A regression test that has never
  gone red is a guess. Revert your change, watch it fail, put it back. Several
  tests in this repository were written that way and two of them were wrong the
  first time — one passed by coincidence because the value it asserted on
  happened to equal an unrelated default.
- **Say why in the docstring.** Not what the test does — the code says that —
  but which failure it exists to prevent.

Do not add tests to raise a coverage number.

---

## High-risk areas

Changes here need a regression test written *before* the change, and a note in
the pull request about what you verified:

- authentication and authorisation (`api/deps.py`, `core/security.py`)
- tenant isolation — the 404-not-403 behaviour is load-bearing
- `services/scoring.py` and anything that feeds it
- evidence encryption (`core/crypto.py`, `services/evidence_store.py`)
- database schema, which has **no migration tool yet** — see ARCHITECTURE.md §8

---

## Commits

One reviewable step per commit, with the reason in the body. Prefer:

```
refactor: extract the authentication domain
fix(report): the stylesheet fell back to an undefined name
test: record the public URL surface as an executable contract
chore: remove unused dependencies
```

A commit body that explains *why*, and what you verified, is worth more than a
long subject line. If you found a bug on the way, say what the old behaviour
was, what the new one is, and how you know.

Do not bundle a rewrite into one enormous commit.
