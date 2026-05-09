"""
Step 4: log in, remove the cookie overlay, wait for the homepage 'My work' list
to populate, click the first case to discover the real interpretation URL,
then walk the 5 tabs (Overview / Quality / Genes / Variants / Report) capturing
HAR + screenshots + per-tab VQS calls.
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
USER = "hackathon1@hackathon.com"
PWD = "Naga942443"


def login(page):
    page.goto(LANDING, wait_until="domcontentloaded")
    page.wait_for_selector("#signInName", timeout=15000)
    page.locator("#signInName").fill(USER)
    page.locator('input[type="password"]').fill(PWD)
    page.locator('input[type="password"]').press("Enter")
    page.wait_for_url(lambda u: "platform-vandv1" in u, timeout=20000)
    page.wait_for_load_state("networkidle", timeout=15000)


def kill_cookie_banner(page):
    # Click the actual "Use necessary cookies only" button. MUI Dialog blocks
    # pointer events through a Backdrop sibling; force=True bypasses that check.
    for sel in [
        'button:has-text("Use necessary cookies only")',
        'button:has-text("Allow all cookies")',
        'button:has-text("Confirm")',
        'button:has-text("Accept")',
    ]:
        try:
            loc = page.locator(sel).first
            if loc.count():
                loc.click(force=True, timeout=3000)
                page.wait_for_timeout(800)
                # Then nuke any leftover MUI Backdrop just in case.
                page.evaluate(
                    """() => {
                        document.querySelectorAll('.MuiBackdrop-root, [class*=Backdrop]').forEach(el => el.remove());
                    }"""
                )
                return sel
        except Exception:
            continue
    return None


def main(headless: bool = True):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, slow_mo=80)
        ctx = browser.new_context(
            record_har_path=str(HAR / "04_walkthrough.har"),
            record_har_mode="full",
            viewport={"width": 1600, "height": 1000},
        )
        page = ctx.new_page()

        api_calls = []
        def on_response(resp):
            url = resp.url
            if "/api/" in url:
                api_calls.append({
                    "method": resp.request.method,
                    "status": resp.status,
                    "url": url,
                    "ts": time.time(),
                })
        page.on("response", on_response)

        print("[1] login")
        login(page)

        print("[2] genomics homepage")
        page.goto(GENOMICS, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle", timeout=20000)
        page.wait_for_timeout(3000)
        kill_cookie_banner(page)
        page.wait_for_timeout(800)
        page.screenshot(path=str(SHOTS / "30_home_clean.png"), full_page=True)

        # Inventory My work and any case link patterns.
        cards = page.evaluate(
            """() => {
                const work = [];
                // Hunt for elements whose text mentions our known sample names.
                const re = /(SG063-LPA|17br088-1-Run1|interpretation-\\d+)/i;
                document.querySelectorAll('a, [role=link], [role=button], button, div, li').forEach(el => {
                    const t = (el.innerText||'').trim();
                    if (t && re.test(t) && t.length < 400) {
                        work.push({
                            tag: el.tagName,
                            href: el.getAttribute('href') || null,
                            text: t.slice(0,200),
                            cls: (el.className||'').toString().slice(0,80),
                        });
                    }
                });
                return work;
            }"""
        )
        (DUMPS / "30_work_cards.json").write_text(json.dumps(cards, indent=2))
        print(f"[3] found {len(cards)} elements mentioning a known case")
        for c in cards[:8]:
            print(f"     {c['tag']} href={c['href']} text={c['text'][:120]!r}")

        # Click the first one that's likely a card or link.
        clicked = False
        if cards:
            # Prefer links/buttons; fall back to first item.
            candidates_priority = [c for c in cards if c["tag"] in ("A","BUTTON")]
            target_text = (candidates_priority or cards)[0]["text"].split("\n")[0][:80]
            print(f"[4] clicking element containing: {target_text!r}")
            try:
                page.get_by_text(target_text, exact=False).first.click(timeout=8000)
                clicked = True
            except Exception as e:
                print(f"   click via text failed: {e}; trying first card directly")
                try:
                    page.locator(f"text={target_text}").first.click(timeout=8000)
                    clicked = True
                except Exception as e2:
                    print(f"   second click attempt failed: {e2}")

        if clicked:
            page.wait_for_load_state("networkidle", timeout=20000)
            page.wait_for_timeout(2500)
            print(f"   url after click: {page.url}")
            print(f"   title: {page.title()}")
            page.screenshot(path=str(SHOTS / "31_after_click.png"), full_page=True)
            (DUMPS / "31_after_click.html").write_text(page.content())

            # Now capture tabs.
            tabs_found = page.evaluate(
                """() => {
                    const tabs = [];
                    document.querySelectorAll('[role=tab]').forEach(t => {
                        const txt = (t.innerText||'').trim();
                        if (txt) tabs.push(txt.slice(0,40));
                    });
                    return tabs;
                }"""
            )
            print(f"[5] tabs visible: {tabs_found}")
            (DUMPS / "31_tabs.json").write_text(json.dumps(tabs_found, indent=2))

            # Walk each known tab name and screenshot.
            for tab_name in ["Overview","Quality","Genes","Variants","Report"]:
                try:
                    pre_count = len(api_calls)
                    page.get_by_role("tab", name=tab_name, exact=False).first.click(timeout=6000)
                    page.wait_for_timeout(2500)
                    try:
                        page.wait_for_load_state("networkidle", timeout=10000)
                    except Exception:
                        pass
                    new_calls = api_calls[pre_count:]
                    vqs = [c for c in new_calls if "/api/variant/query" in c["url"]]
                    print(f"     tab={tab_name}: +{len(new_calls)} api calls, {len(vqs)} VQS")
                    page.screenshot(path=str(SHOTS / f"32_tab_{tab_name.lower()}.png"), full_page=True)
                except Exception as e:
                    print(f"     tab={tab_name} click failed: {e}")

        (DUMPS / "30_api_calls.json").write_text(json.dumps(api_calls, indent=2))
        vqs_total = [c for c in api_calls if "/api/variant/query" in c["url"]]
        print(f"[6] TOTAL: {len(api_calls)} api calls, {len(vqs_total)} VQS")

        ctx.close()
        browser.close()
        print("[done]")


if __name__ == "__main__":
    main(headless="--headed" not in sys.argv)
