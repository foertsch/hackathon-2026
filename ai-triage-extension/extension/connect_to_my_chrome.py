"""
Connect Playwright to YOUR running Chrome via CDP.

Setup (you do this once):
  1. Quit Chrome completely (Cmd-Q, not just close window).
  2. Launch Chrome with the debug port. From a terminal:

        /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome \\
          --remote-debugging-port=9222 \\
          --user-data-dir="$HOME/Library/Application Support/Google/Chrome"

     Use your normal profile path so you stay signed in. Chrome refuses to
     start with --remote-debugging-port if another instance is already
     running with the same profile, hence step 1.

  3. Verify the port is up:
        curl -s http://127.0.0.1:9222/json/version | head -c 80
     You should see the Chrome version JSON.

  4. Run this script. It connects to that Chrome, navigates to the Finder,
     and prints what it sees. Your real account, your profile, your
     extension if you've loaded it via chrome://extensions.
"""

import sys, time
from playwright.sync_api import sync_playwright

CDP_URL = "http://127.0.0.1:9222"
FINDER = "https://platform-vandv1.sophiagenetics.com/web/genomics/finder"


def main():
    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(CDP_URL)
        except Exception as e:
            print(f"could not connect to {CDP_URL}: {e}")
            print()
            print("did you launch Chrome with --remote-debugging-port=9222?")
            print("see the docstring at the top of this file.")
            return 2

        # Connect attaches to the existing Chrome — use its first context.
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        # Find an existing tab on platform-vandv1, or open one.
        page = None
        for p_ in ctx.pages:
            if "platform-vandv1" in p_.url:
                page = p_
                break
        if page is None:
            page = ctx.new_page()
            page.goto(FINDER)
        else:
            page.bring_to_front()

        print(f"connected. tab: {page.url}")
        print(f"title: {page.title()}")
        print()
        print("Tab is yours — close this script when done. Browser stays open.")
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    sys.exit(main() or 0)
