"""Executable architecture rules.

An architecture that is only written down in a document drifts the first time
someone is in a hurry. These tests parse the real import graph and fail the
build when a boundary is crossed, so the rules survive contact with future
contributors.

The layering, outermost first:

    main  ->  api (+schemas)  ->  services  ->  models / db  ->  core

`core` is shared by everything on purpose: configuration, error codes and
crypto have no dependencies of their own.
"""

from __future__ import annotations

import ast
import io
from collections import defaultdict
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parent.parent / "app"

#: Lower number = further out. A module may import its own layer or anything
#: with a higher number. The reverse is a dependency inversion.
LAYERS: dict[str, int] = {
    "app.main": 0,
    "app.api": 1,
    "app.schemas": 1,
    "app.services": 2,
    "app.models": 3,
    "app.db": 3,
    "app.core": 9,
}

#: Modules that legitimately sit outside the layering.
EXEMPT: set[str] = set()


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(APP.parent).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _layer(module: str) -> int:
    for prefix, depth in sorted(LAYERS.items(), key=lambda kv: -len(kv[0])):
        if module == prefix or module.startswith(prefix + "."):
            return depth
    return 99


def _imports(path: Path) -> set[str]:
    """Every `app.*` module this file imports, at module level or inside a
    function. Deferred imports count: moving an import into a function body
    hides a cycle from the interpreter, not from the design."""
    tree = ast.parse(io.open(path, encoding="utf-8").read(), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names if a.name.startswith("app"))
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            if node.module.startswith("app"):
                found.add(node.module)
    return found


def _all_modules() -> dict[str, Path]:
    return {
        _module_name(p): p
        for p in sorted(APP.rglob("*.py"))
        if "__pycache__" not in str(p)
    }


def _graph() -> dict[str, set[str]]:
    modules = _all_modules()
    known = set(modules)
    graph: dict[str, set[str]] = defaultdict(set)
    for name, path in modules.items():
        for target in _imports(path):
            # `from app.models import User` names the package, not a submodule.
            resolved = target
            while resolved and resolved not in known:
                if "." not in resolved:
                    break
                resolved = resolved.rsplit(".", 1)[0]
            if resolved in known and resolved != name:
                graph[name].add(resolved)
    return graph


def test_no_layer_inversions() -> None:
    """No module may depend on a layer further out than its own.

    The concrete failure this prevents: the AI pipeline reaching into an HTTP
    route module to read an evidence file, which made the analysis engine
    unusable outside a web request.
    """
    violations = [
        f"{src} (layer {_layer(src)}) -> {dst} (layer {_layer(dst)})"
        for src, targets in _graph().items()
        for dst in sorted(targets)
        if src not in EXEMPT and _layer(src) > _layer(dst)
    ]
    assert not violations, "dependency inversion:\n  " + "\n  ".join(sorted(violations))


def test_no_route_imports_another_route() -> None:
    """Controllers must not import one another.

    When one route needs another's helper, that helper is a service in the
    wrong place — the fix is to move it down a layer, not to import sideways.
    """
    offenders = [
        f"{src} -> {dst}"
        for src, targets in _graph().items()
        if src.startswith("app.api.routes.")
        for dst in sorted(targets)
        if dst.startswith("app.api.routes.") and dst != src
    ]
    assert not offenders, "route-to-route import:\n  " + "\n  ".join(sorted(offenders))


def test_no_import_cycles() -> None:
    graph = _graph()
    colour: dict[str, int] = {}
    stack: list[str] = []
    cycles: list[str] = []

    def walk(node: str) -> None:
        colour[node] = 1
        stack.append(node)
        for nxt in sorted(graph.get(node, ())):
            if colour.get(nxt, 0) == 0:
                walk(nxt)
            elif colour.get(nxt) == 1:
                cycles.append(" -> ".join(stack[stack.index(nxt):] + [nxt]))
        stack.pop()
        colour[node] = 2

    for node in sorted(graph):
        if colour.get(node, 0) == 0:
            walk(node)
    assert not cycles, "import cycle:\n  " + "\n  ".join(cycles)


def test_domain_does_not_depend_on_the_web_framework() -> None:
    """Scoring is the product's core calculation and must stay portable.

    FR-26 requires it to be deterministic and testable; a FastAPI or SQLAlchemy
    import in that path would make it neither.
    """
    scoring = APP / "services" / "scoring.py"
    source = io.open(scoring, encoding="utf-8").read()
    for forbidden in ("fastapi", "sqlalchemy", "starlette", "app.models", "app.db"):
        assert forbidden not in source, f"scoring.py must not depend on {forbidden}"


@pytest.mark.parametrize("limit,path", [(700, "api/routes/admin"), (600, "services")])
def test_no_module_grows_past_a_reviewable_size(limit: int, path: str) -> None:
    """A file nobody will read in one sitting stops being reviewed.

    The limits are deliberately generous; they exist to catch a module quietly
    accumulating a second responsibility, not to enforce a style.
    """
    target = APP / path
    files = (
        sorted(target.rglob("*.py"))
        if target.is_dir()
        else [target.with_suffix(".py")]
    )
    oversized = {
        str(f.relative_to(APP)): sum(1 for _ in io.open(f, encoding="utf-8"))
        for f in files
        if "__pycache__" not in str(f)
        and sum(1 for _ in io.open(f, encoding="utf-8")) > limit
    }
    assert not oversized, f"module(s) past {limit} lines: {oversized}"
