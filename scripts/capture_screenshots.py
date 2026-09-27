"""
One-off script to capture high-resolution screenshots of the NAZAR frontend
for the presentation deck. Not part of the app's runtime - a build/demo
utility only. Requires the backend (uvicorn, port 8000) and frontend (vite,
port 5173) dev servers already running.

Usage:
    .venv\\Scripts\\python.exe scripts\\capture_screenshots.py
"""

import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE_URL = "http://localhost:5173"
OUT_DIR = Path("docs/screenshots")
VIEWPORT = {"width": 1600, "height": 1000}


def shot(page, name: str, full_page: bool = False, wait: float = 0.6):
    time.sleep(wait)
    page.screenshot(path=str(OUT_DIR / f"{name}.png"), full_page=full_page)
    print(f"  wrote {name}.png")


def click_text(page, text: str, timeout: int = 8000):
    page.get_by_text(text, exact=False).first.click(timeout=timeout)


def close_modal(page):
    """Escape alone can leave the backdrop intercepting clicks if the close
    handler hasn't re-rendered yet - click the explicit close button and
    wait for the panel to actually detach before moving on."""
    if page.locator(".modal-backdrop").count() == 0:
        return
    # Different modals label their close button differently ("Close detail",
    # "Close case detail", "Close match detail") - match by prefix instead of
    # relying on Escape, which is only wired up for the original work-detail
    # modal (see App.tsx's keydown handler tied to `selected`, not
    # `satSelected`/`selectedCase`/`selectedMatch`).
    page.locator(".detail-top button[aria-label^='Close']").first.click(timeout=5000)
    page.wait_for_selector(".modal-backdrop", state="detached", timeout=8000)
    time.sleep(0.3)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=VIEWPORT, device_scale_factor=2)

        # 1. Login / auth page
        page.goto(BASE_URL, wait_until="networkidle")
        shot(page, "01_login_portal")

        # 2. Sign in as Ministry - broadest jurisdiction, full corpus view
        page.fill("#login-user", "ministry")
        page.fill("#login-pass", "ministry-lookcloser-24")
        page.click("button.login-submit")
        page.wait_for_selector("text=A clearer view.", timeout=15000)
        time.sleep(1.2)

        # 3. Overview / dashboard
        page.wait_for_selector("table tbody tr", timeout=15000)
        shot(page, "02_overview_dashboard")

        # 4. Open a flagged work -> detail panel with signals ("an alert")
        page.click("table tbody tr:first-child .work-link")
        page.wait_for_selector(".detail-panel", timeout=10000)
        time.sleep(1)
        shot(page, "03_work_detail_signals")
        # scroll to the explanations / evidence section
        page.evaluate("document.querySelector('.detail-section-heading')?.scrollIntoView()")
        shot(page, "04_work_detail_explanations")

        # Exercise the real Confirm workflow on this work, so the Confirmed
        # tab screenshot later shows an actual reviewed record instead of an
        # empty "0 confirmed" state - a real decision, not staged data.
        try:
            page.fill("#review-reason", "Reviewed the linked evidence and cost signals against the source record - warrants escalation to the state nodal authority for follow-up.")
            page.click(".decision-actions button.primary")
            page.wait_for_selector(".success", timeout=8000)
            time.sleep(0.8)
        except Exception as exc:  # noqa: BLE001
            print("  (could not record a Confirm decision:", exc, ")")
        close_modal(page)

        # 5. Inefficiency tab
        click_text(page, "Inefficiency")
        page.wait_for_selector("text=Where progress is stalled.", timeout=10000)
        shot(page, "05_inefficiency_tab")

        # 6. Confirmed tab
        click_text(page, "Confirmed")
        time.sleep(1)
        shot(page, "06_confirmed_tab")

        # 7. Satellite tab
        click_text(page, "Satellite")
        page.wait_for_selector("text=Remote Sensing Verification", timeout=10000)
        time.sleep(1.2)
        shot(page, "07_satellite_tab_overview")

        # 8. Scroll to the plain-English explainer box
        page.evaluate("window.scrollTo(0, 250)")
        shot(page, "08_satellite_explainer_box")

        # 9. Open a Branch A satellite work -> before/after imagery
        page.evaluate("window.scrollTo(0, 0)")
        page.click("table tbody tr:first-child .work-link")
        page.wait_for_selector(".detail-panel", timeout=10000)
        time.sleep(1.5)
        shot(page, "09_satellite_before_after_imagery")
        close_modal(page)

        # 10. Vendor network section (scroll down on the satellite page)
        page.evaluate("document.querySelector('.related-grid')?.scrollIntoView({block:'center'})")
        shot(page, "10_vendor_network")

        # 11. Cases tab
        page.evaluate("window.scrollTo(0, 0)")
        click_text(page, "Cases")
        try:
            page.wait_for_selector("table tbody tr", timeout=20000)
        except Exception:  # noqa: BLE001
            print("  (no cases in this scope - capturing the empty state as-is)")
        time.sleep(0.8)
        shot(page, "11_cases_tab")

        # 12. Open a case detail
        try:
            page.click("table tbody tr:first-child .work-link", timeout=8000)
            page.wait_for_selector(".detail-panel", timeout=10000)
            time.sleep(1)
            shot(page, "12_case_detail")
            close_modal(page)
        except Exception as exc:  # noqa: BLE001
            print("  (skipped case detail:", exc, ")")

        # 13. Image Evidence tab
        click_text(page, "Image Evidence")
        page.wait_for_selector("table tbody tr", timeout=15000)
        time.sleep(0.8)
        shot(page, "13_image_evidence_tab")

        # 14. Open an image match detail
        try:
            page.click("table tbody tr:first-child .work-link", timeout=8000)
            page.wait_for_selector(".detail-panel", timeout=10000)
            try:
                page.wait_for_selector(".detail-panel img", timeout=8000)
            except Exception:  # noqa: BLE001
                print("  (evidence images did not load in time)")
            time.sleep(1.5)
            shot(page, "14_image_match_detail")
            close_modal(page)
        except Exception as exc:  # noqa: BLE001
            print("  (skipped image match detail:", exc, ")")

        # 15. Data Quality tab
        click_text(page, "Data Quality")
        try:
            # /quality/summary alone measured at ~9-10s server-side over the
            # full corpus - give this real headroom rather than guessing low.
            page.wait_for_selector("text=Loading data-quality alerts", state="detached", timeout=45000)
        except Exception:  # noqa: BLE001
            print("  (data-quality alerts still loading after 45s)")
        time.sleep(0.8)
        shot(page, "15_data_quality_tab")

        browser.close()

    print(f"\nDone - screenshots saved to {OUT_DIR.resolve()}")


if __name__ == "__main__":
    main()
