"""Printing the rendered HTML to PDF.

Isolated because it is the only part of reporting that needs a browser binary
on the host. Keeping it here means a deployment that only serves HTML and JSON
never has to install Chromium.
"""

from __future__ import annotations

from pathlib import Path

# ────────────────────────────── PDF rendering ───────────────────────────────


def render_pdf(html_text: str, out_path: Path) -> Path:
    """Print the HTML through headless Chromium.

    Chosen over the Python PDF libraries because those break Arabic letter
    shaping and bidi ordering; a browser engine gets both right.
    """
    from playwright.sync_api import sync_playwright

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            # `load`, not `networkidle`. The document carries its fonts inline
            # and requests nothing over the network, so there is no idle state
            # worth waiting for — and waiting for one is what made this hang.
            # Measured against a blackholed font host, `networkidle` stalled 30s
            # and then raised, taking the report with it.
            page.set_content(html_text, wait_until="load")
            # Fonts are data URIs, so this resolves without I/O. It is here so
            # the print cannot start mid-swap and lay out Arabic in a fallback
            # face on a slow host.
            page.evaluate("() => document.fonts.ready")
            page.pdf(
                path=str(out_path),
                format="A4",
                print_background=True,
                margin={"top": "16mm", "bottom": "18mm", "left": "14mm", "right": "14mm"},
            )
        finally:
            browser.close()
    return out_path
