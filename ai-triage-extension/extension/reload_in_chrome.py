"""
Reload our unpacked extension in your real Chrome (already running with
--remote-debugging-port=9222) and refresh the active SOPHiA tab.

Run this after every change to content.js / content.css / manifest.json.
Profile-persistent: the extension stays loaded across runs; this just
applies the latest disk state.
"""

import sys
import time
from playwright.sync_api import sync_playwright

CDP_URL = "http://127.0.0.1:9222"
EXT_NAME = "SOPHiA DDM AI Triage"


def main() -> int:
    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(CDP_URL)
        except Exception as e:
            print(f"could not connect to {CDP_URL}: {e}")
            return 2
        ctx = browser.contexts[0]

        ext_tab = ctx.new_page()
        ext_tab.goto("chrome://extensions/")
        time.sleep(1.5)

        # The reload button lives in nested shadow DOM:
        #   extensions-manager > extensions-item-list > extensions-item > #dev-reload-button
        ok = ext_tab.evaluate(
            """(name) => {
                const mgr = document.querySelector('extensions-manager');
                if (!mgr) return 'no manager';
                const items = mgr.shadowRoot
                    ?.querySelector('extensions-item-list')
                    ?.shadowRoot
                    ?.querySelectorAll('extensions-item')
                    || mgr.shadowRoot?.querySelectorAll('extensions-item');
                if (!items?.length) return 'no items';
                for (const item of items) {
                    const sr = item.shadowRoot;
                    const titleEl = sr?.querySelector('#name');
                    if ((titleEl?.textContent || '').trim() !== name) continue;
                    const reloadBtn = sr.querySelector('#dev-reload-button');
                    if (reloadBtn) {
                        reloadBtn.click();
                        return 'reloaded';
                    }
                    return 'no reload button (extension may not be loaded as unpacked)';
                }
                return 'extension not found by name: ' + name;
            }""",
            EXT_NAME,
        )
        print(f"reload result: {ok}")
        ext_tab.close()

        # Refresh the SOPHiA tab if any.
        for page in ctx.pages:
            if "platform-vandv1" in page.url:
                page.reload()
                page.bring_to_front()
                print(f"refreshed: {page.url}")
                break
    return 0 if "reloaded" in str(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
