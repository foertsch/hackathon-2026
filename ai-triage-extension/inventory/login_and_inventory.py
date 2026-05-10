"""
Step 1 of inventory: log into SOPHiA DDM Gen2, screenshot what we land on,
dump the post-login URL and a structural summary of the page so we can
plan the rest of the crawl. Saves a HAR with all network traffic.

Re-runnable. Headed by default so the user can watch.
"""

import os
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

HERE = Path(__file__).parent
SHOTS = HERE / "screenshots"
HAR = HERE / "har"
DUMPS = HERE / "dumps"

LANDING = "https://platform-vandv1.sophiagenetics.com/web/landing"
USER = os.environ.get("HACKATHON_USER", "")
PWD = os.environ.get("HACKATHON_PASSWORD", "")


def main(headless: bool = False):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, slow_mo=120)
        ctx = browser.new_context(
            record_har_path=str(HAR / "01_login.har"),
            record_har_mode="full",
            viewport={"width": 1440, "height": 900},
        )
        page = ctx.new_page()

        print(f"[1] goto {LANDING}")
        page.goto(LANDING, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
        page.screenshot(path=str(SHOTS / "01_landing.png"), full_page=True)
        print(f"   url after landing: {page.url}")
        print(f"   title: {page.title()}")

        # Try common shapes for the login form. Inspect first.
        html_head = page.content()[:2000]
        (DUMPS / "01_landing_head.html").write_text(html_head)

        # Look for email/username and password fields.
        email_locator = None
        # Azure B2C renders the email field with id=signInName after JS init,
        # so wait for it before scanning selectors.
        try:
            page.wait_for_selector("#signInName", timeout=8000)
        except Exception:
            pass
        for sel in [
            "#signInName",
            'input[type="email"]',
            'input[name="email"]',
            'input[name="username"]',
            'input[id*="email" i]',
            'input[id*="user" i]',
            'input[autocomplete="username"]',
        ]:
            if page.locator(sel).count():
                email_locator = sel
                break

        pwd_locator = None
        for sel in [
            'input[type="password"]',
            'input[name="password"]',
            'input[autocomplete="current-password"]',
        ]:
            if page.locator(sel).count():
                pwd_locator = sel
                break

        print(f"[2] selectors found: email={email_locator!r} pwd={pwd_locator!r}")

        if not (email_locator and pwd_locator):
            print("   no login form on landing — capturing what's visible and exiting")
            ctx.close()
            browser.close()
            return

        page.locator(email_locator).first.fill(USER)
        page.locator(pwd_locator).first.fill(PWD)
        page.screenshot(path=str(SHOTS / "02_filled.png"), full_page=True)

        # Submit. Try Enter first (works on most React forms), then a button click as fallback.
        page.locator(pwd_locator).first.press("Enter")
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception as e:
            print(f"   networkidle wait timed out: {e}")

        page.wait_for_timeout(2500)
        page.screenshot(path=str(SHOTS / "03_post_login.png"), full_page=True)
        print(f"[3] url after login: {page.url}")
        print(f"   title: {page.title()}")

        # Dump cookies + storage for later auth reuse.
        cookies = ctx.cookies()
        (DUMPS / "01_cookies.json").write_text(json.dumps(cookies, indent=2))
        try:
            local_storage = page.evaluate(
                "() => Object.fromEntries(Object.entries(localStorage))"
            )
            (DUMPS / "01_localStorage.json").write_text(
                json.dumps(local_storage, indent=2)
            )
        except Exception as e:
            print(f"   localStorage dump failed: {e}")

        # Try to surface IAM token if it's lying around.
        iam_token = None
        for k, v in (local_storage or {}).items():
            if "token" in k.lower() or "access" in k.lower():
                iam_token = (k, v[:60] + "..." if len(v) > 60 else v)
                break
        print(f"   iam token candidate: {iam_token}")

        # Save full HTML of post-login page for navigation discovery.
        (DUMPS / "03_post_login_full.html").write_text(page.content())

        # Capture top-level nav text.
        try:
            nav_text = page.evaluate(
                """() => {
                    const nodes = Array.from(document.querySelectorAll('a, button, [role="link"], [role="button"]'));
                    return nodes.slice(0, 200).map(n => ({
                        text: (n.innerText || '').trim().slice(0, 80),
                        href: n.getAttribute('href') || null,
                        role: n.getAttribute('role') || n.tagName.toLowerCase(),
                    })).filter(x => x.text);
                }"""
            )
            (DUMPS / "03_nav_inventory.json").write_text(json.dumps(nav_text, indent=2))
            print(f"[4] captured {len(nav_text)} nav nodes -> dumps/03_nav_inventory.json")
        except Exception as e:
            print(f"   nav capture failed: {e}")

        ctx.close()
        browser.close()
        print("[done] HAR -> har/01_login.har, shots -> screenshots/, dumps -> dumps/")


if __name__ == "__main__":
    headless = "--headless" in sys.argv
    main(headless=headless)
