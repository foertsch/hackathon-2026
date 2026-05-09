"""
Warm up a Gen2 interpretation by opening it in a headless browser.

Background: SHORT_SUBSET (and its sibling SHORT_GENE_VIEW etc.) are backed by
per-interpretation server-side views like
`main.VIEW_Layer3_PhenRank_defaultTx_joined_with_gene_annotations_interpretation_<ID>_<hash>`.
These views are created lazily — Gen2's frontend triggers their materialization
when a user opens the Interpretation page. If an interpretation has never been
opened, the VQS endpoint 500s on its SHORT_SUBSET.

Workaround: drive a headless Chromium through the same OAuth + page-open flow
the user would, then return. Subsequent VQS calls succeed.

Cost: ~10s per warmup; cached (we don't warm up the same id twice in one run).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

PLATFORM = "https://platform-vandv1.sophiagenetics.com"
LANDING_URL = f"{PLATFORM}/web/landing"
GENOMICS_URL = f"{PLATFORM}/web/gateway/auth/navigate?appPath=/web/genomics"

DEFAULT_USER = "hackathon1@hackathon.com"
DEFAULT_PASSWORD = "Naga942443"

REPO_ROOT = Path(__file__).resolve().parents[2]
WARMED_FILE = REPO_ROOT / "build" / "warmed.json"


def _load_warmed() -> set[str]:
    if WARMED_FILE.exists():
        import json
        try:
            return set(json.loads(WARMED_FILE.read_text()))
        except Exception:
            pass
    return set()


def _save_warmed(ids: set[str]) -> None:
    import json
    WARMED_FILE.parent.mkdir(parents=True, exist_ok=True)
    WARMED_FILE.write_text(json.dumps(sorted(ids)))


def warmup_interpretation(
    interpretation_id: str,
    *,
    user: str = DEFAULT_USER,
    password: str = DEFAULT_PASSWORD,
    timeout_ms: int = 25000,
    skip_if_recent: bool = True,
) -> bool:
    """Open the case in a headless Gen2 session. Returns True if succeeded.

    If `skip_if_recent`, won't re-warm an interpretation we've already warmed
    in this build/ directory.
    """
    if skip_if_recent and interpretation_id in _load_warmed():
        return True

    from playwright.sync_api import sync_playwright

    case_url = f"{PLATFORM}/web/genomics/finder/{interpretation_id}"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()
        try:
            page.goto(LANDING_URL, wait_until="domcontentloaded")
            page.wait_for_selector("#signInName", timeout=15000)
            page.locator("#signInName").fill(user)
            page.locator('input[type="password"]').fill(password)
            page.locator('input[type="password"]').press("Enter")
            page.wait_for_url(lambda u: "platform-vandv1" in u, timeout=20000)
            try:
                page.wait_for_load_state("networkidle", timeout=20000)
            except Exception:
                pass

            # Bootstrap the SPA before deep-linking.
            page.goto(GENOMICS_URL, wait_until="domcontentloaded")
            try:
                page.wait_for_load_state("networkidle", timeout=20000)
            except Exception:
                pass
            time.sleep(2)

            page.goto(case_url, wait_until="domcontentloaded")
            try:
                page.wait_for_load_state("networkidle", timeout=timeout_ms / 1000 * 1000)
            except Exception:
                pass
            time.sleep(4)

            # Click Variants tab so SHORT_SUBSET gets fetched at least once.
            try:
                page.locator("p.MuiTypography-root:text-is('Variants')").first.click(
                    force=True, timeout=5000
                )
                time.sleep(3)
            except Exception:
                pass

            warmed = _load_warmed()
            warmed.add(interpretation_id)
            _save_warmed(warmed)
            return True
        finally:
            ctx.close()
            browser.close()
