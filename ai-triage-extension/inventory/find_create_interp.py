"""
Discover how Gen2 creates an interpretation. We open the Finder, navigate
into a sample that has NO interpretation (SG220-LPA), and look for any
'+ Create' / 'New Interpretation' affordance. Whatever clicks fire are
captured in the HAR.
"""
import os
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HAR_OUT = ROOT / "inventory" / "har" / "06_create_interp.har"

from playwright.sync_api import sync_playwright

USER = os.environ.get("HACKATHON_USER", "")
PWD = os.environ.get("HACKATHON_PASSWORD", "")
LANDING = "https://platform-vandv1.sophiagenetics.com/web/landing"
GENOMICS = "https://platform-vandv1.sophiagenetics.com/web/gateway/auth/navigate?appPath=/web/genomics"
FINDER = "https://platform-vandv1.sophiagenetics.com/web/genomics/finder"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=100)
        ctx = browser.new_context(
            record_har_path=str(HAR_OUT),
            record_har_mode="full",
            viewport={"width": 1500, "height": 1000},
        )
        page = ctx.new_page()

        api_calls = []
        page.on("response", lambda r: api_calls.append({"method": r.request.method, "status": r.status, "url": r.url[:200]}) if "/api/" in r.url else None)

        page.goto(LANDING, wait_until="domcontentloaded")
        page.wait_for_selector("#signInName", timeout=15000)
        page.locator("#signInName").fill(USER)
        page.locator('input[type="password"]').fill(PWD)
        page.locator('input[type="password"]').press("Enter")
        page.wait_for_url(lambda u: "platform-vandv1" in u, timeout=20000)
        try: page.wait_for_load_state("networkidle", timeout=20000)
        except Exception: pass

        page.goto(GENOMICS, wait_until="domcontentloaded")
        try: page.wait_for_load_state("networkidle", timeout=20000)
        except Exception: pass

        # Dismiss cookies
        for sel in ['button:has-text("Use necessary cookies only")', 'button:has-text("Confirm")']:
            try:
                if page.locator(sel).count():
                    page.locator(sel).first.click(force=True, timeout=2000)
                    page.wait_for_timeout(500)
                    break
            except Exception: pass
        page.evaluate("() => document.querySelectorAll('.MuiBackdrop-root, [class*=Backdrop]').forEach(e => e.remove())")

        # Go to Finder
        page.goto(FINDER, wait_until="domcontentloaded")
        try: page.wait_for_load_state("networkidle", timeout=20000)
        except Exception: pass
        time.sleep(3)
        page.screenshot(path=str(ROOT / "inventory" / "screenshots" / "60_finder_requests.png"), full_page=True)

        # Find the Hereditary Cancer row, click its expand chevron (the > on the left)
        try:
            row = page.get_by_role("row").filter(has_text="Hackathon - Hereditary Cancer Run").first
            # Click the first svg/button inside the row (the chevron)
            chevron = row.locator("button, [role=button], svg").first
            chevron.click(timeout=5000)
            time.sleep(2)
            print("clicked chevron")
        except Exception as e:
            print(f"chevron click failed: {e}; trying text click as fallback")
            try:
                page.locator('text=Hackathon - Hereditary Cancer Run').first.click(timeout=5000)
                time.sleep(2)
            except Exception as e2:
                print(f"  fallback also failed: {e2}")
        page.screenshot(path=str(ROOT / "inventory" / "screenshots" / "61_run_expanded.png"), full_page=True)

        # Now look for SG220-LPA, click it
        time.sleep(2)
        try:
            page.locator('text=SG220-LPA').first.click(timeout=8000)
            time.sleep(3)
            print(f"  url after sample click: {page.url}")
        except Exception as e:
            print(f"sample click failed: {e}")
        page.screenshot(path=str(ROOT / "inventory" / "screenshots" / "62_sample_view.png"), full_page=True)

        # Click the Create Interpretation button and capture the API call.
        pre_count = len(api_calls)
        try:
            page.locator('button:has-text("Create interpretation")').first.click(timeout=5000)
            time.sleep(4)
            print(f"  url after create: {page.url}")
            page.screenshot(path=str(ROOT / "inventory" / "screenshots" / "63_after_create.png"), full_page=True)
        except Exception as e:
            print(f"create click failed: {e}")
        new_calls = api_calls[pre_count:]
        print(f"\n{len(new_calls)} api calls fired by 'Create interpretation' click:")
        for c in new_calls:
            print(f"  {c['method']:6} {c['status']} {c['url'][:160]}")

        # Now click the dialog's Create button to actually submit.
        pre = len(api_calls)
        try:
            page.locator('button:has-text("Create")').last.click(timeout=5000)
            time.sleep(5)
            print(f"\nurl after submit: {page.url}")
        except Exception as e:
            print(f"submit click failed: {e}")
        page.screenshot(path=str(ROOT / "inventory" / "screenshots" / "64_after_submit.png"), full_page=True)
        submit_calls = api_calls[pre:]
        print(f"\n{len(submit_calls)} api calls fired by Create submit:")
        for c in submit_calls:
            print(f"  {c['method']:6} {c['status']} {c['url'][:160]}")

        # Dump page text to find buttons
        try:
            buttons = page.evaluate("""
                () => Array.from(document.querySelectorAll('button, [role=button], a')).map(b => ({
                    text: (b.innerText || '').trim().slice(0, 80),
                    aria: b.getAttribute('aria-label'),
                })).filter(x => x.text)
            """)
            interesting = [b for b in buttons if any(k in (b['text'] + (b['aria'] or '')).lower() for k in ['interpret', 'create', 'new', '+', 'open'])]
            print(f"\ninteresting buttons:")
            for b in interesting[:20]:
                print(f"  {b}")
        except Exception as e:
            print(f"button dump failed: {e}")

        # Save api calls
        (ROOT / "inventory" / "dumps" / "60_api_calls.json").write_text(json.dumps(api_calls, indent=2))
        print(f"saved {len(api_calls)} api calls")

        ctx.close()
        browser.close()


if __name__ == "__main__":
    main()
