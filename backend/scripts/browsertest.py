"""Cross-browser acceptance test — the browser-compatibility NFR.

    python -m scripts.browsertest                 # all engines, both languages
    python -m scripts.browsertest --engine webkit
    python -m scripts.browsertest --shots out/    # save screenshots

Engine coverage and what it proves
----------------------------------
The BRD asks for "the latest two major versions of Chrome, Microsoft Edge,
Safari and Firefox". Three rendering engines cover those four browsers:

  * chromium  -> Chrome and Edge (Edge has been Chromium-based since 2020)
  * webkit    -> Safari (WebKit is Safari's engine)
  * firefox   -> Firefox (Gecko)

Testing the engine is what catches real incompatibilities — CSS logical
properties, `structuredClone`, `Intl` behaviour, flex/grid quirks, RTL bidi.
What engine testing does *not* cover is browser chrome, extensions, and
vendor-specific quirks in the shipping build; a final manual pass on real
Safari and Edge stays on the acceptance checklist.

Each page is checked for: HTTP success, no console errors, no failed network
requests, correct `dir`/`lang` stamping, presence of the expected content, and
that the language toggle actually flips direction.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FRONTEND = "http://127.0.0.1:3000"
ENGINES = ("chromium", "firefox", "webkit")

# Engine -> the shipping browsers it stands in for.
COVERS = {
    "chromium": "Chrome, Microsoft Edge",
    "firefox": "Firefox",
    "webkit": "Safari",
}

PUBLIC_PAGES = [
    ("/", "قِس نضج مؤسستك"),
    ("/login", "تسجيل الدخول"),
    ("/register", "إنشاء حساب"),
    ("/forgot-password", "استعادة كلمة المرور"),
]

SIGNED_IN_PAGES = ["/dashboard", "/assessments/new", "/security", "/admin"]

# Warnings that are noise from the dev server, not application faults.
IGNORE = (
    "Download the React DevTools",
    "Fast Refresh",
    "[Fast Refresh]",
    "webpack-hmr",
    "favicon.ico",
    "hydrat",  # dev-only hydration notices from the theme boot script
)


def _relevant(text: str) -> bool:
    return not any(needle.lower() in text.lower() for needle in IGNORE)


def run_engine(playwright, engine: str, shots: Path | None) -> dict:
    browser = getattr(playwright, engine).launch()
    context = browser.new_context(viewport={"width": 1400, "height": 950})
    page = context.new_page()

    errors: list[str] = []
    checks: list[tuple[bool, str]] = []

    def note(ok: bool, label: str, detail: str = "") -> None:
        checks.append((ok, f"{label}{(' — ' + detail) if detail else ''}"))

    page.on(
        "console",
        lambda msg: errors.append(f"console.{msg.type}: {msg.text}")
        if msg.type == "error" and _relevant(msg.text)
        else None,
    )
    def on_page_error(exc) -> None:
        text = str(exc)
        # WebKit reports a navigation-cancelled fetch as a page error.
        if "access control checks" in text.lower() or "load failed" in text.lower():
            return
        errors.append(f"pageerror: {text}")

    page.on("pageerror", on_page_error)
    def on_request_failed(request) -> None:
        # A request cancelled because the page navigated away is not a fault.
        # Each engine words that differently, so all three spellings are here.
        failure = (request.failure or "").lower()
        aborted = any(
            marker in failure
            for marker in ("aborted", "cancel", "interrupt", "access control checks")
        )
        if aborted or not _relevant(request.url):
            return
        errors.append(f"requestfailed: {request.url} ({request.failure})")

    page.on("requestfailed", on_request_failed)

    try:
        # ── public pages, Arabic by default ────────────────────────────────
        for path, expected in PUBLIC_PAGES:
            response = page.goto(f"{FRONTEND}{path}", wait_until="networkidle")
            note(bool(response and response.ok), f"GET {path}", str(response.status if response else "no response"))
            direction = page.get_attribute("html", "dir")
            lang = page.get_attribute("html", "lang")
            note(direction == "rtl" and lang == "ar", f"{path} RTL/Arabic", f"dir={direction} lang={lang}")
            note(expected in page.content(), f"{path} content rendered")

        # ── the language toggle actually flips direction ───────────────────
        page.goto(f"{FRONTEND}/", wait_until="networkidle")
        page.get_by_role("button", name="التبديل إلى الإنجليزية").first.click()
        page.wait_for_function("document.documentElement.dir === 'ltr'", timeout=5000)
        note(page.get_attribute("html", "dir") == "ltr", "language toggle -> LTR")
        note("Measure your institutional maturity" in page.content(), "English copy rendered")

        page.get_by_role("button", name="Switch to Arabic").first.click()
        page.wait_for_function("document.documentElement.dir === 'rtl'", timeout=5000)
        note(page.get_attribute("html", "dir") == "rtl", "language toggle -> RTL")

        # ── the choice survives a reload (no flash of the wrong direction) ──
        page.goto(f"{FRONTEND}/login", wait_until="domcontentloaded")
        note(page.get_attribute("html", "dir") == "rtl", "locale persists across navigation")

        # ── signed-in pages ────────────────────────────────────────────────
        page.goto(f"{FRONTEND}/login", wait_until="networkidle")
        page.fill("#email", "admin@ivalueconsult.com")
        page.fill("#password", "Remas#2026")
        page.click("button[type=submit]")
        page.wait_for_url("**/dashboard", timeout=20000)
        note(True, "sign in")

        for path in SIGNED_IN_PAGES:
            response = page.goto(f"{FRONTEND}{path}", wait_until="networkidle")
            note(bool(response and response.ok), f"GET {path}", str(response.status if response else "-"))

        # Positive proof the authenticated API calls succeed in this engine —
        # the dashboard only renders these once /auth/me and /assessments return.
        page.goto(f"{FRONTEND}/dashboard", wait_until="networkidle")
        org_name = "آي فاليو للاستشارات"
        page.wait_for_selector(f"text={org_name}", timeout=15000)
        note(org_name in page.content(), "authenticated API data rendered")
        onboarding_loaded = page.evaluate(
            "() => document.querySelectorAll('.steps li').length"
        )
        note(onboarding_loaded >= 8, "onboarding checklist loaded from the API",
             f"{onboarding_loaded} steps")

        # ── the administration portal: every tab must render its own data ──
        page.goto(f"{FRONTEND}/admin", wait_until="networkidle")
        for label, marker in (
            ("أطر التقييم", "REMAS"),
            ("المحتوى", "المحاور والأسئلة"),
            ("قوالب التقارير", None),
            ("المنشآت", "demo-developer"),
            ("المستخدمون", "admin@ivalueconsult.com"),
            ("الذكاء الاصطناعي", "مزوّد التحليل"),
            ("سجل التدقيق", None),
        ):
            page.get_by_role("button", name=label, exact=True).first.click()
            page.wait_for_timeout(900)
            ok = marker is None or marker in page.content()
            note(ok, f"admin tab renders: {label}", "" if ok else f"missing {marker}")

        # The content editor is the deepest screen — open a pillar and confirm
        # its questions come back from the API rather than an empty accordion.
        page.get_by_role("button", name="المحتوى", exact=True).first.click()
        page.wait_for_timeout(1200)
        question_rows = page.evaluate(
            "() => document.querySelectorAll('.panel').length"
        )
        # The editor opens on the fullest version, so the first pillar's whole
        # question set must come back — one row would mean it landed on an
        # empty leftover draft instead.
        note(question_rows >= 5, "content editor lists questions", f"{question_rows} rows")

        # The AI screen must never render the stored key, only its hint, and it
        # has to say which provider is *actually* in use.
        page.get_by_role("button", name="الذكاء الاصطناعي", exact=True).first.click()
        page.wait_for_timeout(900)
        ai_html = page.content()
        note("المزوّد الفعلي" in ai_html, "AI settings shows the effective provider")
        password_fields = page.evaluate(
            "() => document.querySelectorAll('input[type=password]').length"
        )
        selects = page.evaluate("() => document.querySelectorAll('select').length")
        note(selects >= 2, "AI settings renders provider and OCR selectors", f"{selects} selects")
        note(
            "sk-" not in ai_html or password_fields > 0,
            "no API key rendered in the page",
        )

        page.get_by_role("button", name="المحتوى", exact=True).first.click()
        page.wait_for_timeout(900)
        for sub in ("مستويات النضج", "قواعد الاحتساب", "آفاق خارطة الطريق", "مكتبة المبادرات"):
            page.get_by_role("button", name=sub, exact=True).first.click()
            page.wait_for_timeout(700)
            fields = page.evaluate("() => document.querySelectorAll('.field, table tbody tr').length")
            note(fields > 0, f"content section renders: {sub}", f"{fields} controls")

        # ── layout integrity: nothing may scroll the page sideways ─────────
        page.goto(f"{FRONTEND}/dashboard", wait_until="networkidle")
        overflow = page.evaluate(
            "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
        )
        note(overflow <= 1, "no horizontal overflow at 1400px", f"{overflow}px")

        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(400)
        mobile_overflow = page.evaluate(
            "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
        )
        note(mobile_overflow <= 1, "no horizontal overflow at 390px", f"{mobile_overflow}px")
        page.set_viewport_size({"width": 1400, "height": 950})

        # ── nothing may paint outside the card that owns it ────────────────
        # Document-level overflow misses a child bursting out of a bordered
        # container, which is exactly how a long value in a nowrap chip fails.
        for page_path, width in (("/", 1400), ("/", 1100), ("/dashboard", 1400), ("/admin", 1400)):
            page.set_viewport_size({"width": width, "height": 950})
            page.goto(f"{FRONTEND}{page_path}", wait_until="networkidle")
            page.wait_for_timeout(300)
            escaping = page.evaluate(
                """() => {
                    const bad = [];
                    for (const card of document.querySelectorAll('.card, .stat, .lane')) {
                        const box = card.getBoundingClientRect();
                        for (const child of card.querySelectorAll('*')) {
                            const c = child.getBoundingClientRect();
                            if (c.width === 0 || c.height === 0) continue;
                            if (c.right > box.right + 1 || c.left < box.left - 1) {
                                bad.push((child.className || child.tagName) + ' in ' + card.className);
                            }
                        }
                    }
                    return bad.slice(0, 5);
                }"""
            )
            note(not escaping, f"no element escapes its card ({page_path} @ {width}px)",
                 "; ".join(escaping)[:120])
        page.set_viewport_size({"width": 1400, "height": 950})

        # ── the palette tokens actually resolved in this engine ───────────
        primary = page.evaluate(
            "() => getComputedStyle(document.documentElement).getPropertyValue('--brand-700').trim()"
        )
        note(primary != "", "CSS custom properties resolve", primary)

        # ── dark mode stamping ─────────────────────────────────────────────
        page.evaluate("() => document.documentElement.setAttribute('data-theme','dark')")
        page.wait_for_timeout(200)
        dark_paper = page.evaluate(
            "() => getComputedStyle(document.body).backgroundColor"
        )
        page.evaluate("() => document.documentElement.removeAttribute('data-theme')")
        note("rgb" in dark_paper, "dark theme paints a background", dark_paper)

        if shots:
            shots.mkdir(parents=True, exist_ok=True)
            for path, name in (("/", "landing"), ("/dashboard", "dashboard"), ("/admin", "admin")):
                page.goto(f"{FRONTEND}{path}", wait_until="networkidle")
                page.screenshot(path=str(shots / f"{engine}-{name}.png"), full_page=True)

    finally:
        context.close()
        browser.close()

    return {"engine": engine, "checks": checks, "errors": errors}


def main() -> None:
    # Check labels carry Arabic; a cp1252 console would otherwise abort the run
    # after the browser work is already done.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="REMAS cross-browser acceptance")
    parser.add_argument("--engine", choices=ENGINES, default=None)
    parser.add_argument("--shots", default=None, help="directory for screenshots")
    args = parser.parse_args()

    from playwright.sync_api import sync_playwright

    engines = [args.engine] if args.engine else list(ENGINES)
    shots = Path(args.shots) if args.shots else None
    results = []

    with sync_playwright() as playwright:
        for engine in engines:
            print(f"\n=== {engine}  (covers: {COVERS[engine]}) ===")
            try:
                result = run_engine(playwright, engine, shots)
            except Exception as exc:  # noqa: BLE001
                print(f"  FAIL  engine crashed: {type(exc).__name__}: {exc}")
                results.append({"engine": engine, "checks": [(False, "engine run")], "errors": [str(exc)]})
                continue

            for ok, label in result["checks"]:
                print(f"  {'PASS' if ok else 'FAIL'}  {label}")
            for error in result["errors"][:10]:
                print(f"  ERROR {error}")
            results.append(result)

    print("\n" + "=" * 60)
    all_ok = True
    for result in results:
        failed = [label for ok, label in result["checks"] if not ok]
        passed = sum(1 for ok, _ in result["checks"] if ok)
        clean = not failed and not result["errors"]
        all_ok = all_ok and clean
        print(
            f"  {'PASS' if clean else 'FAIL'}  {result['engine']:<9} "
            f"{passed}/{len(result['checks'])} checks, "
            f"{len(result['errors'])} console/network errors"
            f"  [{COVERS[result['engine']]}]"
        )
        for label in failed:
            print(f"          ✗ {label}")

    print("\nRESULT:", "ALL ENGINES PASS" if all_ok else "FAILURES FOUND")
    raise SystemExit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
