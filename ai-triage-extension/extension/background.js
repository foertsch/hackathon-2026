// SOPHiA DDM AI Triage — background service worker
//
// Content scripts are bound by the page's CORS / Private Network Access
// rules even when host_permissions are granted. Fetches initiated from
// this service worker run with extension origin privileges instead, so
// the loopback (http://127.0.0.1:8000) calls go through.
//
// Protocol: content script sends { type: "fetch", url, init } and gets
// back { ok, status, body, error }.

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg && msg.type === "fetch") {
    (async () => {
      try {
        const r = await fetch(msg.url, msg.init || {});
        const text = await r.text();
        sendResponse({ ok: r.ok, status: r.status, body: text });
      } catch (e) {
        sendResponse({ ok: false, status: 0, error: String(e) });
      }
    })();
    return true; // keep the message channel open for the async sendResponse
  }
});
