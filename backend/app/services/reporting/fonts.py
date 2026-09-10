"""The report's typefaces, embedded rather than fetched.

Why this module exists
----------------------
The report HTML used to pull its fonts from `fonts.googleapis.com`, and
`render_pdf` waits for `networkidle` before printing. That made a customer's
final report depend on the render host reaching Google. Measured, on this
machine, with the font host intercepted three ways:

    reachable                     1.28s   correct typography
    connection refused            0.61s   silently different glyphs
    egress blackholed            30.08s   TimeoutError — no PDF at all

The third row is the ordinary shape of a locked-down corporate network: egress
is dropped, not refused. `release_report` calls `render_pdf` unguarded, so that
row is a bare 500 on the one action the whole assessment builds toward.

The second row is worse in a quieter way — it succeeds, so nobody investigates,
and the Arabic simply comes out in a fallback face.

Embedding the files removes the dependency instead of adding a timeout around
it: there is no request to fail, and the report looks the same on every host
regardless of what fonts that host happens to have installed.

Licence
-------
IBM Plex and Readex Pro are both SIL Open Font License 1.1, which permits
embedding and redistribution. See `fonts/LICENSE.md`.

Subsetting
----------
Google serves each weight split by script, and the report is bilingual, so both
the `arabic` and `latin` subsets are kept for every weight and re-declared with
their original `unicode-range`. Keeping only the largest subset per weight —
the obvious shortcut — silently drops Latin glyphs, which would have left the
English report in a fallback face while the Arabic one looked perfect.

Cost
----
14 woff2 files, ~291 KB, base64-inlined once per process and cached.
"""

from __future__ import annotations

import base64
import json
from functools import lru_cache
from pathlib import Path

FONT_DIR = Path(__file__).resolve().parent / "fonts"
MANIFEST = FONT_DIR / "manifest.json"


class MissingFontError(RuntimeError):
    """A declared face is absent from the package.

    Raised loudly rather than skipped: a silently missing face is the failure
    this module exists to prevent, and it would otherwise surface as a report
    that renders perfectly well in the wrong typeface.
    """


def _faces() -> list[dict]:
    if not MANIFEST.exists():
        raise MissingFontError(f"{MANIFEST} is missing; the report fonts are not installed.")
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def face_css() -> str:
    """`@font-face` rules with the font bytes inlined as data URIs.

    Data URIs rather than file paths because the renderer hands Chromium a
    string through `set_content`, which has no base URL for a relative
    `url(...)` to resolve against.
    """
    rules: list[str] = []
    for face in _faces():
        path = FONT_DIR / face["file"]
        if not path.exists():
            raise MissingFontError(
                f"{face['file']} is listed in manifest.json but missing from "
                f"{FONT_DIR}. Restore it rather than letting the report fall "
                f"back to whatever the render host has installed."
            )
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        rule = (
            "@font-face{"
            f"font-family:'{face['family']}';font-style:normal;"
            f"font-weight:{face['weight']};font-display:block;"
            f"src:url(data:font/woff2;base64,{encoded}) format('woff2');"
        )
        if face.get("unicode_range"):
            rule += f"unicode-range:{face['unicode_range']};"
        rules.append(rule + "}")
    return "\n".join(rules)


def available() -> bool:
    """Whether every declared face is present — used by the readiness probe, so
    a deployment missing its fonts is visible before a customer asks for a PDF."""
    try:
        return all((FONT_DIR / f["file"]).exists() for f in _faces())
    except MissingFontError:
        return False
