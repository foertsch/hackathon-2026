"""
Step 5: navigate directly to interpretation-1047 (Hereditary Cancer / SG063-LPA),
walk the 5 tabs by clicking the <p>Tab</p> text, capture per-tab API traffic.
Save the Variants tab's full row payload for downstream report design.
"""
import json
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

HERE = Path(__file__).parent
SHOTS = HERE / "screenshots"
HAR = HERE / "har"
DUMPS = HERE / "dumps"

LANDING = "https://platform-vandv1.sophiagenetics.com/web/landing"
GENOMICS = "https://platform-vandv1.sophiagenetics.com/web/gateway/auth/navigate?appPath=/web/genomics"
INTERP_URL = "https://platform-vandv1.sophiagenetics.com/web/genomics/finder/interpretation-1047"
USER = "hackathon1@hackathon.com"
PWD = "Naga942443"
TABS = ["Overview", "Quality", "Genes", "Variants", "Report"]


def login(page):
    page.goto(LANDING, wait_until="domcontentloaded")
    page.wait_for_selector("#signInName", timeout=15000)
    page.locator("#signInName").fill(USER)
    page.locator('input[type="password"]').fill(PWD)
    page.locator('input[type="password"]').press("Enter")
    page.wait_for_url(lambda u: "platform-vandv1" in u, timeout=20000)
    page.wait_for_load_state("networkidle", timeout=15000)


def kill_cookie_banner(page):
    for sel in [
        'button:has-text("Use necessary cookies only")',
        'button:has-text("Allow all cookies")',
        'button:has-text("Confirm")',
    ]:
        try:
            loc = page.locator(sel).first
            if loc.count():
                loc.click(force=True, timeout=2000)
                page.wait_for_timeout(500)
                page.evaluate(
                    "() => document.querySelectorAll('.MuiBackdrop-root, [class*=Backdrop]').forEach(e => e.remove())"
                )
                return sel
        except Exception:
            pass
    return None


def main(headless: bool = True):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, slow_mo=80)
        ctx = browser.new_context(
            record_har_path=str(HAR / "05_tabs.har"),
            record_har_mode="full",
            viewport={"width": 1600, "height": 1000},
        )
        page = ctx.new_page()

        api_calls = []
        # Track per-tab call ranges by storing index marks.
        def on_response(resp):
            if "/api/" in resp.url:
                api_calls.append({
                    "method": resp.request.method,
                    "status": resp.status,
                    "url": resp.url,
                    "ts": time.time(),
                })
        page.on("response", on_response)

        print("[1] login")
        login(page)
        print("[2] genomics home + dismiss cookies")
        page.goto(GENOMICS, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle", timeout=20000)
        page.wait_for_timeout(2000)
        kill_cookie_banner(page)

        print(f"[3] direct nav to {INTERP_URL}")
        page.goto(INTERP_URL, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=25000)
        except Exception:
            pass
        page.wait_for_timeout(3500)
        page.screenshot(path=str(SHOTS / "50_interp_overview.png"), full_page=True)
        print(f"   url: {page.url}")

        per_tab = {}
        for tab in TABS:
            print(f"[tab] {tab}")
            pre = len(api_calls)
            try:
                # Click the <p>Tab</p> element. MUI wraps it in a clickable div;
                # clicking the <p> bubbles up and triggers the handler.
                target = page.locator(f"p.MuiTypography-root:text-is('{tab}')").first
                if not target.count():
                    target = page.get_by_text(tab, exact=True).first
                target.scroll_into_view_if_needed(timeout=4000)
                target.click(force=True, timeout=6000)
                page.wait_for_timeout(2500)
                try:
                    page.wait_for_load_state("networkidle", timeout=12000)
                except Exception:
                    pass
                page.wait_for_timeout(1500)
            except Exception as e:
                print(f"   click failed: {e}")
                per_tab[tab] = {"error": str(e)[:200]}
                continue
            new_calls = api_calls[pre:]
            vqs = [c for c in new_calls if "/api/variant/query" in c["url"]]
            per_tab[tab] = {"new_api": len(new_calls), "vqs": len(vqs)}
            print(f"   +{len(new_calls)} api, {len(vqs)} VQS")
            page.screenshot(path=str(SHOTS / f"51_{tab.lower()}.png"), full_page=True)
            (DUMPS / f"50_{tab.lower()}.html").write_text(page.content())

        (DUMPS / "50_per_tab_summary.json").write_text(json.dumps(per_tab, indent=2))
        (DUMPS / "50_all_api_calls.json").write_text(json.dumps(api_calls, indent=2))
        print(f"[done] total api={len(api_calls)}")

        ctx.close()
        browser.close()


if __name__ == "__main__":
    main(headless="--headed" not in sys.argv)
