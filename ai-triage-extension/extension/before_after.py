"""
Capture matched before/after screenshots demonstrating the AI summary card
injected into the SAMPLE/ANALYSIS side panel. Both screenshots show the
Hereditary Cancer Run expanded in the Finder with the side panel open on
the BRCA2 HIGH-priority sample.
"""

import os
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

EXT_DIR = Path(__file__).resolve().parent
ROOT = EXT_DIR.parent
PROFILE = ROOT / "build" / "_chrome_profile_compare"
LANDING = "https://platform-vandv1.sophiagenetics.com/web/landing"
GENOMICS = "https://platform-vandv1.sophiagenetics.com/web/gateway/auth/navigate?appPath=/web/genomics"
FINDER = "https://platform-vandv1.sophiagenetics.com/web/genomics/finder"
USER = os.environ.get("HACKATHON_USER", "")
PWD = os.environ.get("HACKATHON_PASSWORD", "")
VIEWPORT = {"width": 1500, "height": 1100}
TARGET_SAMPLE = "17br088-1-Run1"


def login(page):
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


def dismiss_cookies(page):
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


def open_side_panel_on_target(page):
    page.goto(GENOMICS, wait_until="domcontentloaded")
    try: page.wait_for_load_state("networkidle", timeout=15000)
    except Exception: pass
    dismiss_cookies(page)
    page.goto(FINDER, wait_until="domcontentloaded")
    try: page.wait_for_load_state("networkidle", timeout=15000)
    except Exception: pass
    time.sleep(3)
    # Expand Hereditary Cancer Run via aria-label="see children".
    rows = page.locator('[role=row]:has-text("Hereditary Cancer Run")')
    if rows.count():
        rows.first.locator('button[aria-label="see children"]').click(force=True)
        time.sleep(2)
    # Click the target sample to open the side panel.
    try:
        page.locator(f"text={TARGET_SAMPLE}").first.click(force=True, timeout=8000)
        time.sleep(3)
    except Exception as e:
        print(f"sample click failed: {e}")


def capture(with_extension: bool, out_path: Path):
    with sync_playwright() as p:
        if with_extension:
            args = [
                f"--disable-extensions-except={EXT_DIR}",
                f"--load-extension={EXT_DIR}",
                "--no-first-run",
                "--no-default-browser-check",
            ]
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE),
                headless=False,
                channel="chrome",
                args=args,
                viewport=VIEWPORT,
            )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
        else:
            browser = p.chromium.launch(headless=False)
            ctx = browser.new_context(viewport=VIEWPORT)
            page = ctx.new_page()

        login(page)
        open_side_panel_on_target(page)

        if with_extension:
            # Wait for the AI card to appear with real content.
            for _ in range(20):
                ready = page.locator(
                    "#sophia-sidepanel-card:not(.sophia-loading)"
                ).count()
                if ready:
                    break
                time.sleep(1)
            time.sleep(2)
        else:
            time.sleep(2)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(out_path), full_page=False)
        print(f"saved {out_path.relative_to(ROOT)}")
        ctx.close()


def main():
    import shutil
    if PROFILE.exists():
        shutil.rmtree(PROFILE)
    capture(with_extension=False, out_path=ROOT / "build" / "before.png")
    if PROFILE.exists():
        shutil.rmtree(PROFILE)
    capture(with_extension=True, out_path=ROOT / "build" / "after.png")

    from PIL import Image, ImageDraw, ImageFont
    a = Image.open(ROOT / "build" / "before.png").convert("RGB")
    b = Image.open(ROOT / "build" / "after.png").convert("RGB")
    gap = 30
    label_h = 44
    width = a.width + b.width + gap
    height = max(a.height, b.height) + label_h
    out = Image.new("RGB", (width, height), (240, 243, 248))
    draw = ImageDraw.Draw(out)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 18)
    except Exception:
        font = ImageFont.load_default()
    draw.rectangle((0, 0, a.width, label_h), fill=(13, 34, 64))
    draw.text((24, 12),
              "BEFORE — sample side panel (no AI assistance)",
              fill=(255, 255, 255), font=font)
    draw.rectangle((a.width + gap, 0, width, label_h), fill=(233, 17, 87))
    draw.text((a.width + gap + 24, 12),
              "AFTER — AI Triage card injected at the top of the panel",
              fill=(255, 255, 255), font=font)
    out.paste(a, (0, label_h))
    out.paste(b, (a.width + gap, label_h))
    out.save(ROOT / "build" / "before_after.png")
    print(f"composite: {ROOT / 'build' / 'before_after.png'}  ({out.size[0]}x{out.size[1]})")


if __name__ == "__main__":
    main()
