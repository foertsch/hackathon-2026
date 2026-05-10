"""
Step 2: from a fresh login, jump straight into the Genomics module,
inventory what's on the homepage (lists of runs / analyses / interpretations),
grab the IAM bearer token, and dump the page structure for planning.
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
IAM_TOKEN_URL = "https://iam-vandv.sophiagenetics.com/account/token"
USER = os.environ.get("HACKATHON_USER", "")
PWD = os.environ.get("HACKATHON_PASSWORD", "")


def login(page):
    page.goto(LANDING, wait_until="domcontentloaded")
    page.wait_for_selector("#signInName", timeout=15000)
    page.locator("#signInName").fill(USER)
    page.locator('input[type="password"]').fill(PWD)
    page.locator('input[type="password"]').press("Enter")
    page.wait_for_url(lambda u: "platform-vandv1" in u, timeout=20000)
    page.wait_for_load_state("networkidle", timeout=15000)


def dismiss_cookies(page):
    for label in ["Use necessary cookies only", "Allow all cookies", "Confirm"]:
        try:
            btn = page.get_by_role("button", name=label, exact=False)
            if btn.count():
                btn.first.click(timeout=2000)
                page.wait_for_timeout(500)
                return label
        except Exception:
            pass
    return None


def main(headless: bool = True):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, slow_mo=80)
        ctx = browser.new_context(
            record_har_path=str(HAR / "02_genomics.har"),
            record_har_mode="full",
            viewport={"width": 1440, "height": 900},
        )
        page = ctx.new_page()

        # Track interesting API calls.
        api_calls = []
        def on_response(resp):
            url = resp.url
            if "/api/" in url or "iam-vandv" in url:
                api_calls.append({
                    "method": resp.request.method,
                    "status": resp.status,
                    "url": url[:300],
                })
        page.on("response", on_response)

        print("[1] login")
        login(page)
        dismissed = dismiss_cookies(page)
        print(f"   cookies dismissed via: {dismissed}")

        print(f"[2] goto genomics")
        page.goto(GENOMICS, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle", timeout=20000)
        page.wait_for_timeout(2500)
        page.screenshot(path=str(SHOTS / "10_genomics_home.png"), full_page=True)
        print(f"   url: {page.url}")
        print(f"   title: {page.title()}")
        (DUMPS / "10_genomics_home.html").write_text(page.content())

        print("[3] try IAM token endpoint")
        try:
            tok = page.request.get(IAM_TOKEN_URL)
            print(f"   {tok.status} {tok.url}")
            body = tok.text()
            (DUMPS / "10_iam_token.json").write_text(body)
            try:
                j = json.loads(body)
                if isinstance(j, dict) and "access_token" in j:
                    print(f"   access_token (first 30): {j['access_token'][:30]}...")
            except Exception:
                pass
        except Exception as e:
            print(f"   token fetch failed: {e}")

        print("[4] inventory page structure")
        try:
            inv = page.evaluate(
                """() => {
                    const out = { headings: [], links: [], buttons: [], inputs: [], tables: 0 };
                    document.querySelectorAll('h1,h2,h3,h4').forEach(h => {
                        const t = (h.innerText||'').trim();
                        if (t) out.headings.push({ tag: h.tagName, text: t.slice(0,120) });
                    });
                    document.querySelectorAll('a[href]').forEach(a => {
                        const t = (a.innerText||'').trim();
                        const h = a.getAttribute('href') || '';
                        if (t && t.length < 200) out.links.push({ text: t.slice(0,120), href: h });
                    });
                    document.querySelectorAll('button, [role=button]').forEach(b => {
                        const t = (b.innerText||'').trim();
                        if (t) out.buttons.push(t.slice(0,80));
                    });
                    document.querySelectorAll('input, select, textarea').forEach(i => {
                        out.inputs.push({
                            tag: i.tagName,
                            type: i.getAttribute('type') || '',
                            name: i.getAttribute('name') || '',
                            placeholder: i.getAttribute('placeholder') || '',
                        });
                    });
                    out.tables = document.querySelectorAll('table, [role=grid], [role=table]').length;
                    return out;
                }"""
            )
            (DUMPS / "10_genomics_structure.json").write_text(json.dumps(inv, indent=2))
            print(f"   headings: {len(inv['headings'])}  links: {len(inv['links'])}  buttons: {len(inv['buttons'])}  tables: {inv['tables']}")
            for h in inv["headings"][:15]:
                print(f"     {h['tag']}: {h['text']}")
        except Exception as e:
            print(f"   structure capture failed: {e}")

        # Save accumulated API calls.
        (DUMPS / "10_api_calls.json").write_text(json.dumps(api_calls, indent=2))
        print(f"[5] saw {len(api_calls)} api/iam calls")
        for c in api_calls[-15:]:
            print(f"     {c['method']} {c['status']} {c['url'][:160]}")

        ctx.close()
        browser.close()
        print("[done]")


if __name__ == "__main__":
    main(headless="--headed" not in sys.argv)
