"""Undefined names and dead imports fail the build.

This gate earned its place. `styles.py` referenced a maturity-ramp constant
that lived in another module and was never imported; the `or RAMP` fallback
short-circuited whenever branding supplied a ramp, so every ordinary report
rendered fine and the fault sat there waiting for a template that omitted one.
Code review had not caught it in five refactors. Pyflakes caught it in under a
second.

Two rules are enforced:

* **undefined name** — a NameError that has not been triggered yet. Always a
  defect; there is no legitimate reason to reference a name that is not there.
* **unused import** — usually harmless, occasionally the visible end of a
  half-finished move. Suppressed with `# noqa: F401` where an import exists for
  its side effect, which is the real case here: `import app.models` registers
  the SQLAlchemy mappers and is never referenced by name.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

from pyflakes import reporter as pyflakes_reporter
from pyflakes.api import checkPath

ROOT = Path(__file__).resolve().parent.parent
TARGETS = ("app", "scripts", "tests")

#: Findings that are legitimate and permanently suppressed at the source line
#: with `# noqa: F401`. Anything else is a failure.
SUPPRESSED = "# noqa"


def _findings() -> list[str]:
    out, err = io.StringIO(), io.StringIO()
    reporter = pyflakes_reporter.Reporter(out, err)
    for target in TARGETS:
        for path in sorted((ROOT / target).rglob("*.py")):
            if "__pycache__" in str(path):
                continue
            checkPath(str(path), reporter)
    return [line for line in out.getvalue().splitlines() if line.strip()]


#: `PATH:LINE:COL: message`. Anchored on the digits rather than split on ":",
#: because a Windows path carries a drive-letter colon of its own.
_FINDING = re.compile(r"^(?P<path>.+):(?P<line>\d+):\d+: (?P<message>.*)$")


def _is_suppressed(finding: str) -> bool:
    """A finding is allowed only if its own source line carries `# noqa`."""
    match = _FINDING.match(finding)
    if match is None:
        return False
    try:
        source = Path(match["path"]).read_text(encoding="utf-8").splitlines()
        return SUPPRESSED in source[int(match["line"]) - 1]
    except (OSError, IndexError):
        return False


def test_no_undefined_names() -> None:
    """The class of finding that is always a real bug."""
    offenders = [f for f in _findings() if "undefined name" in f]
    assert not offenders, (
        "undefined name(s) — each one is a NameError waiting for the right "
        "input:\n  " + "\n  ".join(offenders)
    )


def test_no_unexplained_unused_imports() -> None:
    """Dead imports are allowed only where the import is the point."""
    offenders = [
        f
        for f in _findings()
        if "imported but unused" in f and not _is_suppressed(f)
    ]
    assert not offenders, (
        "unused import(s). If the import exists for a side effect, mark the "
        "line `# noqa: F401` with the reason:\n  " + "\n  ".join(offenders)
    )
