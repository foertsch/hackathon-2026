# Chrome extension (Manifest V3)

The browser-side half of [`ai-triage-extension/`](../). For installation,
configuration, and what this extension does, see the
[**project README**](../README.md).

## Files

- `manifest.json` — MV3 manifest. Content script declared on
  `platform-vandv1.sophiagenetics.com/web/genomics*`; service worker for
  background fetches; loopback `http://127.0.0.1:8000/*` listed in
  `host_permissions`.
- `content.js` — observes the Gen2 SPA via `MutationObserver`, finds the
  side panel by tag-text matching, injects the triage card and chat.
- `background.js` — fetch proxy. Loopback calls from the HTTPS page origin
  are blocked under Chrome's Private Network Access policy; the service
  worker performs them with extension-origin privileges.
- `content.css` — styling for everything injected.
- `*.py` — Playwright helpers used during dev iteration (reload extension,
  before/after screenshots). Not shipped.

## Reloading after edits

In `chrome://extensions/`, click the reload icon on the **SOPHiA DDM AI
Triage + Chatbot** card. Content script + CSS pick up immediately on the
next Gen2 navigation; the service worker may need a tab refresh to rebind.
