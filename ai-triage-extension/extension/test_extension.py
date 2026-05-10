"""
End-to-end test: launch a Chromium with our extension loaded, log in to
Gen2, wait for the AI panels to inject, screenshot the result.

Requires the backend running at 127.0.0.1:8000.
"""

import os
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

EXT_DIR = Path(__file__).resolve().parent
ROOT = EXT_DIR.parent
LANDING = "https://platform-vandv1.sophiagenetics.com/web/landing"
GENOMICS = "https://platform-vandv1.sophiagenetics.com/web/gateway/auth/navigate?appPath=/web/genomics"
USER = os.environ.get("HACKATHON_USER", "")
PWD = os.environ.get("HACKATHON_PASSWORD", "")

OUT = ROOT / "build" / "extension_screenshot.png"


def main():
    with sync_playwright() as p:
        # Persistent context is required to load unpacked extensions.
        # Headless extensions in Chromium require new headless mode.
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(ROOT / "build" / "_chrome_profile"),
            headless=False,
            args=[
                f"--disable-extensions-except={EXT_DIR}",
                f"--load-extension={EXT_DIR}",
                "--no-first-run",
                "--no-default-browser-check",
            ],
            viewport={"width": 1600, "height": 1100},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        page.goto(LANDING, wait_until="domcontentloaded")
        page.wait_for_selector("#signInName", timeout=15000)
        page.locator("#signInName").fill(USER)
        page.locator('input[type="password"]').fill(PWD)
        page.locator('input[type="password"]').press("Enter")
        page.wait_for_url(lambda u: "platform-vandv1" in u, timeout=20000)
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass

        # Bootstrap the SPA via Genomics first, then go to the Finder.
        page.goto(GENOMICS, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass

        # Dismiss the cookie banner so the worklist is fully visible.
        for sel in [
            'button:has-text("Use necessary cookies only")',
            'button:has-text("Allow all cookies")',
            'button:has-text("Confirm")',
        ]:
            try:
                loc = page.locator(sel).first
                if loc.count():
                    loc.click(force=True, timeout=2000)
                    page.wait_for_timeout(600)
                    break
            except Exception:
                pass
        page.evaluate(
            "() => document.querySelectorAll('.MuiBackdrop-root, [class*=Backdrop]').forEach(e => e.remove())"
        )

        # Now go to the Finder, the analysis index page.
        page.goto(
            "https://platform-vandv1.sophiagenetics.com/web/genomics/finder",
            wait_until="domcontentloaded",
        )
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        time.sleep(2)
        # Click the Interpretations tab.
        try:
            page.locator('button:has-text("Interpretations")').first.click(timeout=5000)
            time.sleep(2)
        except Exception:
            pass

        # Allow time for content script to find rows and inject panels.
        for i in range(15):
            time.sleep(1.5)
            n = page.locator(".sophia-card").count()
            ready = page.locator(".sophia-card:not(.sophia-loading)").count()
            print(f"  [{i+1}] sophia cards: {n} (ready: {ready})")
            if ready >= 5:
                break

        time.sleep(3)
        OUT.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(OUT), full_page=True)
        print(f"saved {OUT}")
        ctx.close()


if __name__ == "__main__":
    main()
