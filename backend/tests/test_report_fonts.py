"""The report must not reach the network to render.

Background
----------
The report HTML used to link `fonts.googleapis.com`, and `render_pdf` waited
for `networkidle` before printing. Measured on a development machine with the
font host intercepted three ways:

    reachable                     1.28s   correct typography
    connection refused            0.61s   renders, in the wrong face, silently
    egress blackholed            30.08s   TimeoutError — no PDF produced

The last row is the ordinary shape of a locked-down corporate network: egress
is dropped rather than refused. `release_report` calls `render_pdf` unguarded,
so that row was a bare 500 on the single action an entire assessment builds up
to. The middle row is worse in a quieter way, because it succeeds.

The fix embeds the faces. These tests guard the two properties that keep it
fixed: the document asks for nothing remote, and the printer no longer waits
for a network that has nothing to say.
"""

from __future__ import annotations

import json

from app.services.reporting import fonts


def test_every_declared_face_is_present() -> None:
    """A missing file would not raise — it would render the report in whatever
    the host happens to have, which is exactly the silent failure being fixed."""
    assert fonts.available(), "a declared font file is missing from the package"


def test_manifest_covers_arabic_and_latin_for_every_family() -> None:
    """The report is bilingual. Keeping only the largest subset per weight is
    the obvious shortcut and it drops Latin, leaving the English report in a
    fallback face while the Arabic one looks perfect.

    IBM Plex Mono is Latin-only by design and is excluded from the Arabic half.
    """
    manifest = json.loads((fonts.FONT_DIR / "manifest.json").read_text(encoding="utf-8"))
    subsets: dict[str, set[str]] = {}
    for face in manifest:
        subsets.setdefault(face["family"], set()).add(face["subset"])

    for family, present in subsets.items():
        assert "latin" in present, f"{family} has no Latin subset"
        if family != "IBM Plex Mono":
            assert "arabic" in present, f"{family} has no Arabic subset"


def test_font_css_declares_a_unicode_range_per_face() -> None:
    """Without the range, the Latin subset would claim the whole codepoint
    space and the browser would never fall through to the Arabic file."""
    css = fonts.face_css()
    assert css.count("@font-face") == css.count("unicode-range:"), (
        "every embedded face must carry the unicode-range it was subset for"
    )
    assert "U+0600" in css, "no face claims the Arabic block"


def test_printer_does_not_wait_for_network_idle() -> None:
    """`networkidle` is what turned an unreachable font host into a hang. With
    every asset inline there is no idle state worth waiting for."""
    source = (fonts.FONT_DIR.parent / "pdf.py").read_text(encoding="utf-8")
    assert 'wait_until="networkidle"' not in source, (
        "render_pdf waits for network idle again; an unreachable external asset "
        "will stall the report for the full Playwright timeout and then fail it"
    )
    assert 'wait_until="load"' in source
