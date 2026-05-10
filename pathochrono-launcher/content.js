// PathoChrono Launcher — content script.
//
// Finds the "Welcome" greeting on the Gen2 landing/genomics page and inserts
// a "Scheduler" button right next to it. Re-injects across SPA navigation
// via a MutationObserver. The button just opens the chronotype scheduler
// in a new tab — no backend, no fetches.

const SCHEDULER_URL = "https://patho-chrono-flow.lovable.app/";
const BUTTON_ID = "pathochrono-launcher-btn";

// Match the smallest element whose own text starts with "Welcome".
// Use elements with no children that have the same text (i.e. leaf-ish nodes)
// to avoid grabbing the whole page body.
function findWelcomeElement() {
  const candidates = document.querySelectorAll(
    "h1, h2, h3, h4, span, div, p, section"
  );
  for (const el of candidates) {
    const t = (el.textContent || "").trim();
    if (!t.toLowerCase().startsWith("welcome")) continue;
    // Skip wrappers — prefer the deepest element matching.
    const childMatch = Array.from(el.children).some(
      (c) => (c.textContent || "").trim().toLowerCase().startsWith("welcome")
    );
    if (childMatch) continue;
    return el;
  }
  return null;
}

function buildButton() {
  const a = document.createElement("a");
  a.id = BUTTON_ID;
  a.className = "pathochrono-launcher-btn";
  a.href = SCHEDULER_URL;
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  a.textContent = "Scheduler";
  a.title = "Open the chronotype-aware scheduler";
  return a;
}

function injectIfNeeded() {
  if (document.getElementById(BUTTON_ID)) return;
  const welcome = findWelcomeElement();
  if (!welcome) return;
  const btn = buildButton();
  // Place the button immediately after the Welcome element, in the same row.
  // Wrap in an inline-flex container if the parent isn't already flex,
  // so the button sits on the same line.
  welcome.insertAdjacentElement("afterend", btn);
}

// Initial pass + observe DOM mutations so we re-inject after SPA route
// changes redraw the landing page.
injectIfNeeded();
const observer = new MutationObserver(() => injectIfNeeded());
observer.observe(document.body, { childList: true, subtree: true });
