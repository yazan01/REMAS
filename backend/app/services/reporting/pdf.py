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
            page.set_content(html_text, wait_until="networkidle")
            page.pdf(
                path=str(out_path),
                format="A4",
                print_background=True,
                margin={"top": "16mm", "bottom": "18mm", "left": "14mm", "right": "14mm"},
            )
        finally:
            browser.close()
    return out_path
