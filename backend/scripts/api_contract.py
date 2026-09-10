"""The recorded public HTTP surface, and the tool that regenerates it.

Why this exists
---------------
Restructuring controllers is the refactor most likely to move a URL by
accident: a router gains a prefix, a route moves to a package that already has
one, and the path silently becomes `/admin/admin/...`. Nothing in the type
system catches that, and no unit test notices — but every deployed client does.

So the surface is recorded as data (`tests/api_contract.txt`) and asserted by
`tests/test_api_contract.py`. Moving code between modules leaves that file
untouched; moving a *URL* shows up as a reviewable diff.

Regenerate only when a contract change is intended:

    python -m scripts.api_contract --write

and treat the resulting diff as the API-change section of the pull request.
"""

from __future__ import annotations

import argparse
from pathlib import Path

CONTRACT = Path(__file__).resolve().parent.parent / "tests" / "api_contract.txt"

HEADER = """\
# The public HTTP surface of REMAS, one line per method+path.
#
# Regenerated deliberately with:  python -m scripts.api_contract --write
# A refactor must never change this file. If a diff appears here, the
# refactor moved a URL and every existing client breaks with it.
"""


def current_surface() -> list[str]:
    """Every method+path FastAPI actually publishes, read from the OpenAPI
    document rather than from `app.routes` — the schema is what clients and the
    generated docs consume, so it is the contract that matters."""
    from app.main import app

    spec = app.openapi()
    return sorted(
        f"{method.upper()} {path}"
        for path, operations in spec["paths"].items()
        for method in operations
    )


def recorded_surface() -> list[str]:
    return [
        line
        for line in CONTRACT.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]


def write() -> int:
    routes = current_surface()
    CONTRACT.write_text(HEADER + "\n".join(routes) + "\n", encoding="utf-8")
    return len(routes)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write", action="store_true", help="record the current surface as the contract"
    )
    args = parser.parse_args()
    if args.write:
        print(f"recorded {write()} routes in {CONTRACT}")
        return
    added = sorted(set(current_surface()) - set(recorded_surface()))
    removed = sorted(set(recorded_surface()) - set(current_surface()))
    for route in added:
        print(f"+ {route}")
    for route in removed:
        print(f"- {route}")
    print("no drift" if not (added or removed) else f"{len(added)} added, {len(removed)} removed")


if __name__ == "__main__":
    main()
