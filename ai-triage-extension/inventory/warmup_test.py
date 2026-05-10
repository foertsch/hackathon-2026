"""
Test whether opening an interpretation in Gen2's frontend ('warming' it)
makes its VQS endpoint stop 500-ing.
"""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright

USER = os.environ.get("HACKATHON_USER", "")
PWD = os.environ.get("HACKATHON_PASSWORD", "")
LANDING = "https://platform-vandv1.sophiagenetics.com/web/landing"
INTERP_ID = "interpretation-1046"
URL = f"https://platform-vandv1.sophiagenetics.com/web/genomics/finder/{INTERP_ID}"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()

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

        # Go through genomics first to ensure SPA bootstrap
        page.goto("https://platform-vandv1.sophiagenetics.com/web/gateway/auth/navigate?appPath=/web/genomics", wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        time.sleep(3)
        print(f"  genomics url: {page.url}")

        print(f"opening {URL}")
        page.goto(URL, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=25000)
        except Exception:
            pass
        time.sleep(5)
        print(f"  url: {page.url}")
        print(f"  title: {page.title()}")

        # Now drive Variants tab so VQS calls happen
        try:
            page.locator(f"p.MuiTypography-root:text-is('Variants')").first.click(force=True, timeout=5000)
            time.sleep(3)
            print("  clicked Variants")
        except Exception as e:
            print(f"  Variants click failed: {e}")

        ctx.close()
        browser.close()
    print("done")


if __name__ == "__main__":
    main()
