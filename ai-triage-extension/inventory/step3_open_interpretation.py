"""
Step 3: open interpretation-1042 directly (the one the API docs use), let Gen2
load it, click through the 5 tabs (Overview, Quality, Genes, Variants, Report),
and capture all the VQS + GraphQL traffic per tab.

We discover the right URL by trying the obvious shape; if that fails we fall
back to the home page and click into the case via UI.
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
GENOMICS = "https://platform-vandv1.sophiagenetics.com/web/gateway/auth/navigate?appPath=/web/genomics"
USER = os.environ.get("HACKATHON_USER", "")
PWD = os.environ.get("HACKATHON_PASSWORD", "")

INTERP_ID = "interpretation-1042"
ANALYSIS_ID = "200042360"


def login(page):
    page.goto(LANDING, wait_until="domcontentloaded")
    page.wait_for_selector("#signInName", timeout=15000)
    page.locator("#signInName").fill(USER)
    page.locator('input[type="password"]').fill(PWD)
    page.locator('input[type="password"]').press("Enter")
    page.wait_for_url(lambda u: "platform-vandv1" in u, timeout=20000)
    page.wait_for_load_state("networkidle", timeout=15000)


def main(headless: bool = True):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, slow_mo=80)
        ctx = browser.new_context(
            record_har_path=str(HAR / "03_interpretation.har"),
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
                })
        page.on("response", on_response)

        print("[1] login")
        login(page)
        print("[2] go to genomics homepage to land in the SPA")
        page.goto(GENOMICS, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle", timeout=20000)

        # Try direct URL into interpretation. SPAs typically do hash or path routing.
        candidates = [
            f"https://platform-vandv1.sophiagenetics.com/web/genomics/interpretation/{INTERP_ID}",
            f"https://platform-vandv1.sophiagenetics.com/web/genomics/analyses/{ANALYSIS_ID}/interpretations/{INTERP_ID}",
            f"https://platform-vandv1.sophiagenetics.com/web/genomics/case/{INTERP_ID}",
        ]
        loaded = False
        for u in candidates:
            print(f"[3] try direct: {u}")
            page.goto(u, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            t = page.title()
            print(f"   -> title={t}, url={page.url}")
            # Heuristic: did we land somewhere with variant content?
            content = page.content().lower()
            if "variant" in content and "interpretation" in content:
                loaded = True
                break
        if not loaded:
            print("   direct URL did not surface variant content; falling back to homepage")
            page.goto(GENOMICS, wait_until="domcontentloaded")
            page.wait_for_load_state("networkidle", timeout=15000)
            page.wait_for_timeout(2000)

        page.screenshot(path=str(SHOTS / "20_interpretation_loaded.png"), full_page=True)
        (DUMPS / "20_interpretation.html").write_text(page.content())

        # Inventory the page: tabs, headings, table-like elements.
        try:
            inv = page.evaluate(
                """() => {
                    const out = { headings: [], tabs: [], buttons: [], tableLike: 0, totalCells: 0 };
                    document.querySelectorAll('h1,h2,h3,h4').forEach(h => {
                        const t=(h.innerText||'').trim();
                        if(t) out.headings.push({tag:h.tagName, text:t.slice(0,140)});
                    });
                    document.querySelectorAll('[role=tab], .tab, [class*=tab i]').forEach(b => {
                        const t=(b.innerText||'').trim();
                        if(t && t.length<60) out.tabs.push(t);
                    });
                    document.querySelectorAll('button').forEach(b => {
                        const t=(b.innerText||'').trim();
                        if(t && t.length<60) out.buttons.push(t);
                    });
                    out.tableLike = document.querySelectorAll('table, [role=grid], [role=table], .ag-root, .ag-grid').length;
                    out.totalCells = document.querySelectorAll('[role=row], tr').length;
                    return out;
                }"""
            )
            (DUMPS / "20_interpretation_structure.json").write_text(json.dumps(inv, indent=2))
            print(f"[4] structure: {len(inv['headings'])} headings, {len(set(inv['tabs']))} tabs, {inv['tableLike']} table-like nodes, {inv['totalCells']} rows")
            for h in inv["headings"][:10]:
                print(f"     {h['tag']}: {h['text']}")
            print(f"     tabs: {sorted(set(inv['tabs']))[:20]}")
        except Exception as e:
            print(f"   structure capture failed: {e}")

        # Save accumulated API calls.
        (DUMPS / "20_api_calls.json").write_text(json.dumps(api_calls, indent=2))
        vqs = [c for c in api_calls if "/api/variant/query" in c["url"]]
        print(f"[5] saw {len(api_calls)} api calls, {len(vqs)} VQS")
        for c in vqs[:10]:
            print(f"     {c['method']} {c['status']} {c['url'][:160]}")

        ctx.close()
        browser.close()
        print("[done]")


if __name__ == "__main__":
    main(headless="--headed" not in sys.argv)
