"""The public URL surface is a contract, and this test is where it is kept.

BRD section 15 says existing APIs must not break unnecessarily, and that any
breaking change is documented with a migration path. That promise needs a
mechanism, not a good intention: the failure it guards against is a controller
split that silently relocates a URL — a router picks up a prefix it did not
have, a path gains or loses a segment, and the change passes every other test
because the handler itself still works.

`tests/api_contract.txt` records every method+path. Moving a handler between
modules must leave it byte-identical. Changing it is allowed, but only as a
deliberate act with a visible diff:

    python -m scripts.api_contract --write
"""

from __future__ import annotations

from scripts.api_contract import current_surface, recorded_surface


def test_public_url_surface_has_not_drifted() -> None:
    current = set(current_surface())
    recorded = set(recorded_surface())

    added = sorted(current - recorded)
    removed = sorted(recorded - current)

    assert not removed, (
        "route(s) disappeared from the API — every existing client calling them "
        "now gets a 404:\n  " + "\n  ".join(removed)
    )
    assert not added, (
        "route(s) appeared that the contract does not record. If this is "
        "intended, run `python -m scripts.api_contract --write` and review the "
        "diff as part of the change:\n  " + "\n  ".join(added)
    )


def test_no_duplicate_paths_in_the_contract() -> None:
    """A duplicate means two handlers answer the same method+path and one of
    them is unreachable — FastAPI resolves the first and never reports it."""
    recorded = recorded_surface()
    duplicates = sorted({r for r in recorded if recorded.count(r) > 1})
    assert not duplicates, f"duplicate route(s): {duplicates}"
