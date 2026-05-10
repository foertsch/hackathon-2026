"""
Authenticate against SOPHiA DDM Gen2 and produce a `requests.Session` ready
to call /api/* endpoints.

Flow:
  1. Drive the Azure B2C OAuth login once with Playwright (headless).
  2. Copy session cookies onto a `requests.Session`.
  3. Hit `/web/gateway/api/auth/session` to get `iam_access_token`.
  4. Attach `Authorization: Bearer <token>` to the session.

Cache state to `build/auth.json`. On 401 or `iam_exp` past, re-login.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

import requests

PLATFORM = "https://platform-vandv1.sophiagenetics.com"
LANDING_URL = f"{PLATFORM}/web/landing"
SESSION_URL = f"{PLATFORM}/web/gateway/api/auth/session"

DEFAULT_USER = os.environ.get("HACKATHON_USER", "")
DEFAULT_PASSWORD = os.environ.get("HACKATHON_PASSWORD", "")

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_FILE = REPO_ROOT / "build" / "auth.json"


def _login_with_playwright(user: str, password: str) -> list[dict]:
    """Run B2C OAuth in headless Chromium, return cookies for platform-vandv1."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto(LANDING_URL, wait_until="domcontentloaded")
        page.wait_for_selector("#signInName", timeout=15000)
        page.locator("#signInName").fill(user)
        page.locator('input[type="password"]').fill(password)
        page.locator('input[type="password"]').press("Enter")
        page.wait_for_url(lambda u: "platform-vandv1" in u, timeout=20000)
        page.wait_for_load_state("networkidle", timeout=15000)
        cookies = ctx.cookies()
        browser.close()
    return cookies


def _build_session(cookies: list[dict]) -> requests.Session:
    s = requests.Session()
    for c in cookies:
        s.cookies.set(
            c["name"],
            c["value"],
            domain=c.get("domain"),
            path=c.get("path", "/"),
        )
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "*/*",
        "Origin": PLATFORM,
        "Referer": f"{PLATFORM}/web/genomics/",
    })
    return s


def _fetch_bearer(session: requests.Session) -> tuple[str, int]:
    r = session.get(SESSION_URL, timeout=15)
    r.raise_for_status()
    payload = r.json()
    token = payload.get("iam_access_token")
    if not token:
        raise RuntimeError(f"No iam_access_token in session response: keys={list(payload)[:10]}")
    exp = int(payload.get("exp") or (time.time() + 3000))
    return token, exp


def _save_cache(cookies: list[dict], token: str, exp: int) -> None:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps({"cookies": cookies, "token": token, "exp": exp}))


def _load_cache() -> Optional[dict]:
    if not CACHE_FILE.exists():
        return None
    try:
        d = json.loads(CACHE_FILE.read_text())
    except Exception:
        return None
    if int(d.get("exp", 0)) - 60 < time.time():
        return None
    return d


def get_session(
    user: str = DEFAULT_USER,
    password: str = DEFAULT_PASSWORD,
    *,
    force_refresh: bool = False,
) -> requests.Session:
    """Return an authenticated `requests.Session` with bearer + cookies set."""
    cached = None if force_refresh else _load_cache()
    if cached:
        session = _build_session(cached["cookies"])
        session.headers["Authorization"] = f"Bearer {cached['token']}"
        # Smoke-test the session.
        r = session.get(SESSION_URL, timeout=10)
        if r.status_code == 200:
            return session

    cookies = _login_with_playwright(user, password)
    session = _build_session(cookies)
    token, exp = _fetch_bearer(session)
    session.headers["Authorization"] = f"Bearer {token}"
    _save_cache(cookies, token, exp)
    return session


if __name__ == "__main__":
    s = get_session()
    r = s.get(SESSION_URL, timeout=10)
    info = r.json()
    print(f"OK: user={info.get('sub')} client={info.get('client', {}).get('name')} exp_in={int(info.get('exp', 0)) - int(time.time())}s")
