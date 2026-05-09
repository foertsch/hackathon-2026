"""
Fast iteration helper for the extension.

Run once: launches Chromium with our extension loaded under a persistent
profile. Logs in once. Then on each subsequent invocation it reuses the
same profile (no relogin) — fresh extension code is picked up because
Chrome reads the unpacked extension from disk on each context launch.

Usage:
    python3 extension/dev_iterate.py            # full demo flow + screenshot
    python3 extension/dev_iterate.py --console  # also stream console logs
    python3 extension/dev_iterate.py --keep     # leave the browser open

The persistent profile lives at build/_chrome_profile_dev. To start over
(e.g. credentials changed), delete that directory.
"""

import argparse
import shutil
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

EXT_DIR = Path(__file__).resolve().parent
ROOT = EXT_DIR.parent
PROFILE = ROOT / "build" / "_chrome_profile_dev"
LANDING = "https://platform-vandv1.sophiagenetics.com/web/landing"
GENOMICS = "https://platform-vandv1.sophiagenetics.com/web/gateway/auth/navigate?appPath=/web/genomics"
FINDER = "https://platform-vandv1.sophiagenetics.com/web/genomics/finder"
USER = "hackathon1@hackathon.com"
PWD = "Naga942443"
TARGET_SAMPLE = "17br088-1-Run1"


def login_if_needed(page):
    page.goto(LANDING, wait_until="domcontentloaded")
    try:
        page.wait_for_selector("#signInName", timeout=4000)
    except Exception:
        return False  # already signed in
    page.locator("#signInName").fill(USER)
    page.locator('input[type="password"]').fill(PWD)
    page.locator('input[type="password"]').press("Enter")
    page.wait_for_url(lambda u: "platform-vandv1" in u, timeout=20000)
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    return True


def dismiss_cookies(page):
    for sel in [
        'button:has-text("Use necessary cookies only")',
        'button:has-text("Confirm")',
    ]:
        try:
            if page.locator(sel).count():
                page.locator(sel).first.click(force=True, timeout=2000)
                page.wait_for_timeout(500)
                break
        except Exception:
            pass
    page.evaluate(
        "() => document.querySelectorAll('.MuiBackdrop-root, [class*=Backdrop]').forEach(e => e.remove())"
    )


def navigate(page):
    page.goto(GENOMICS, wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    dismiss_cookies(page)
    page.goto(FINDER, wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    time.sleep(2)
    rows = page.locator('[role=row]:has-text("Hereditary Cancer Run")')
    if rows.count():
        try:
            rows.first.locator('button[aria-label="see children"]').click(force=True)
            time.sleep(2)
        except Exception:
            pass
    try:
        page.locator(f"text={TARGET_SAMPLE}").first.click(force=True, timeout=8000)
        time.sleep(4)
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--console", action="store_true", help="stream console logs")
    ap.add_argument("--keep", action="store_true", help="leave the browser open after the run")
    ap.add_argument("--reset", action="store_true", help="wipe the persistent profile first")
    args = ap.parse_args()

    if args.reset and PROFILE.exists():
        shutil.rmtree(PROFILE)

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE),
            headless=False,
            channel="chrome",
            args=[
                f"--disable-extensions-except={EXT_DIR}",
                f"--load-extension={EXT_DIR}",
                "--no-first-run",
                "--no-default-browser-check",
            ],
            # Compensate for the ~60px automation banner Playwright requires
            # by giving the viewport extra vertical room.
            viewport={"width": 1500, "height": 1180},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        if args.console:
            page.on("console", lambda m: print(f"[c.{m.type}] {m.text[:280]}"))
            page.on("pageerror", lambda e: print(f"[err] {str(e)[:200]}"))

        relogged = login_if_needed(page)
        print(f"login: {'fresh' if relogged else 'reused profile'}")

        navigate(page)
        # Wait for AI card to render.
        for i in range(12):
            ready = page.locator("#sophia-sidepanel-card:not(.sophia-loading)").count()
            print(f"  [t={i}] AI card ready: {ready}")
            if ready:
                break
            time.sleep(1.5)

        out = ROOT / "build" / "after.png"
        page.screenshot(path=str(out), full_page=False)
        print(f"saved {out.relative_to(ROOT)}")

        if args.keep:
            print("--keep: browser stays open. Ctrl-C to close.")
            try:
                while True:
                    time.sleep(60)
            except KeyboardInterrupt:
                pass
        ctx.close()


if __name__ == "__main__":
    sys.exit(main() or 0)
