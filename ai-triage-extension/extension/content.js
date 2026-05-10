// SOPHiA DDM AI Triage — content script (side-panel mode)
//
// When a sample/analysis side panel opens in Gen2, we inject an AI summary
// card at the top of its content area. Pre-warm summaries for every sample
// in any visibly-expanded run so the panel populates instantly.

const BACKEND = "http://127.0.0.1:8000";
const PANEL_CARD_ID = "sophia-sidepanel-card";
const PANEL_CHAT_ID = "sophia-sidepanel-chat";

let allRuns = null;
let samplesByUserRef = {};      // userRef -> { id, ngs_run_id, ... }
let summariesBySampleId = {};
let prewarmed = new Set();
let inflightFetches = new Map(); // sampleId -> Promise
let chatBySampleId = {};         // sampleId -> [{role, content}]

// ---- API helpers ----
//
// Fetches go through the background service worker so they use extension
// origin privileges (Private Network Access / CORS rules don't block
// loopback calls from the extension origin the way they do from the page).

function bgFetch(url, init) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage({ type: "fetch", url, init }, (resp) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }
      if (!resp) { reject(new Error("no response from background")); return; }
      if (!resp.ok) {
        reject(new Error(resp.error || `HTTP ${resp.status}`));
        return;
      }
      try { resolve(JSON.parse(resp.body)); }
      catch (_) { resolve(resp.body); }
    });
  });
}

async function loadRuns() {
  if (allRuns) return allRuns;
  try {
    const data = await bgFetch(`${BACKEND}/api/runs`);
    allRuns = data.runs || [];
    return allRuns;
  } catch (e) {
    console.warn("[SOPHiA AI Triage] /api/runs failed:", e);
    return null;
  }
}

async function loadRunSamples(runId) {
  try {
    const data = await bgFetch(`${BACKEND}/api/run/${runId}/samples`);
    for (const s of data.samples || []) {
      if (s.user_ref) samplesByUserRef[s.user_ref] = s;
    }
    return data.samples || [];
  } catch (e) {
    console.warn(`[SOPHiA AI Triage] run/${runId}/samples failed:`, e);
    return [];
  }
}

async function prewarmRun(runId) {
  if (prewarmed.has(runId)) return;
  prewarmed.add(runId);
  try {
    await bgFetch(`${BACKEND}/api/run/${runId}/prewarm`, { method: "POST" });
  } catch (e) {
    console.warn(`[SOPHiA AI Triage] prewarm ${runId} failed:`, e);
  }
}

function fetchSampleSummary(sampleId) {
  if (summariesBySampleId[sampleId]) return Promise.resolve(summariesBySampleId[sampleId]);
  if (inflightFetches.has(sampleId)) return inflightFetches.get(sampleId);
  const p = (async () => {
    const envelope = await bgFetch(`${BACKEND}/api/sample-summary/${sampleId}`);
    summariesBySampleId[sampleId] = envelope;
    return envelope;
  })();
  inflightFetches.set(sampleId, p);
  p.finally(() => inflightFetches.delete(sampleId));
  return p;
}

// ---- DOM helpers ----

function findPanel() {
  // The right-side detail panel contains the literal text "SAMPLE/ANALYSIS"
  // followed by tabs (Information / Output files / Input files). Match the
  // smallest ancestor that contains those three texts and is reasonably wide.
  const candidates = [];
  document.querySelectorAll("div, section, aside").forEach((el) => {
    const t = (el.innerText || "");
    if (
      t.includes("SAMPLE/ANALYSIS") &&
      t.includes("Information") &&
      t.includes("Output files") &&
      el.offsetWidth > 280 && el.offsetWidth < 720
    ) {
      candidates.push(el);
    }
  });
  if (!candidates.length) return null;
  // Smallest such element = innermost panel container.
  candidates.sort((a, b) => a.offsetWidth * a.offsetHeight - b.offsetWidth * b.offsetHeight);
  return candidates[0];
}

function findSampleNameInPanel(panel) {
  // The sample name shows near the top of the panel, often alongside an
  // "RUO" pill. Strategy:
  //  1. Try exact-text match (cleanest).
  //  2. Fall back to startsWith in case the heading element wraps the
  //     userRef plus a sibling badge.
  //  3. Last resort: scan the panel's full innerText for any known userRef.
  //     This avoids missing the sample when its name is split across nodes.
  const refs = Object.keys(samplesByUserRef).sort((a, b) => b.length - a.length);
  if (!refs.length) return null;
  const candidates = panel.querySelectorAll("h1, h2, h3, h4, h5, h6, p, span, div");
  for (const el of candidates) {
    const t = (el.innerText || "").trim();
    if (refs.includes(t)) return { element: el, userRef: t };
  }
  for (const el of candidates) {
    const t = (el.innerText || "").trim();
    for (const ref of refs) {
      if (t === ref + "\nRUO" || t.startsWith(ref + "\n") || t.startsWith(ref + " ")) {
        return { element: el, userRef: ref };
      }
    }
  }
  // Last resort: see which userRef the panel mentions at all.
  const panelText = panel.innerText || "";
  for (const ref of refs) {
    if (panelText.includes(ref)) {
      return { element: null, userRef: ref };
    }
  }
  return null;
}

function findInjectionPoint(panel) {
  // Try multiple anchors so we land somewhere sensible regardless of state.
  const all = panel.querySelectorAll("p, span, div");
  for (const anchorText of ["Item status", "Application", "Restriction", "MID"]) {
    for (const el of all) {
      if ((el.innerText || "").trim() === anchorText) {
        // Walk up to a row container that spans most of the panel width.
        let host = el;
        for (let i = 0; i < 6 && host && host.parentElement; i++) {
          host = host.parentElement;
          if (host.offsetWidth >= panel.offsetWidth - 60) return host;
        }
        return el.parentElement;
      }
    }
  }
  return null;
}

// ---- Card rendering ----

function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// Known ACMG / ClinVar classification + review-status tokens. Snake-case in
// the data; we render them with spaces, italicised, so they read as natural
// medical phrases. Sorted longest-first so longer tokens match before any
// substring (e.g. Conflicting_… before Pathogenic).
const CLASSIFICATION_TOKENS = [
  "Conflicting_classifications_of_pathogenicity",
  "criteria_provided,_multiple_submitters,_no_conflicts",
  "criteria_provided,_single_submitter",
  "no_assertion_criteria_provided",
  "reviewed_by_expert_panel",
  "Uncertain_significance",
  "practice_guideline",
  "Likely_pathogenic",
  "Likely_benign",
  "Risk_factor",
  "Drug_response",
  "not_provided",
  "Pathogenic",
  "Benign",
  "Affects",
  "VUS",
].sort((a, b) => b.length - a.length);

function escapeRegex(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function formatClassifications(text) {
  // Escape HTML first, then wrap classification tokens in <i> with spaces.
  let out = escapeHtml(text);
  for (const token of CLASSIFICATION_TOKENS) {
    const display = token.replace(/_/g, " ");
    const re = new RegExp("\\b" + escapeRegex(token) + "(?=\\b|$|[\\s.,;:])", "g");
    out = out.replace(re, `<i class="sophia-class">${display}</i>`);
  }
  return out;
}

// Pretty names for indicator codes that come from the bundle. Falls back to
// the description string if a code isn't mapped here.
const QC_INDICATOR_LABELS = {
  cov_unif: "Coverage uniformity",
  panel_cov_percentile_200: "Proportion of target regions with coverage ≥200×",
  onTarget_bases: "On-target read rate",
};

function fmtQcValue(v) {
  if (v === null || v === undefined || v === "") return "N/A";
  if (typeof v === "number") {
    if (v >= 1 && v <= 100) return v.toFixed(3);
    if (v < 1) return v.toFixed(3);
    return String(v);
  }
  return String(v);
}

function fmtQcRange(low, high) {
  if (low === null || high === null || low === undefined || high === undefined) return "";
  const fmt = (x) => String(x); // 1.0 → "1", 0.99 → "0.99", 100 → "100"
  return `expected ${fmt(low)}–${fmt(high)}`;
}

function renderQcIndicatorRows(indicators) {
  return (indicators || [])
    .map((ind) => {
      const label = QC_INDICATOR_LABELS[ind.name] || ind.description || ind.name;
      const status = (ind.status || "UNKNOWN").toUpperCase();
      const isFail = status === "FAILED" || status === "FAIL";
      const isPass = status === "PASSED" || status === "PASS";
      const cls = isFail ? "sophia-qc-FAIL" : isPass ? "sophia-qc-PASS" : "sophia-qc-WARN";
      const pill = isFail ? "Fail" : isPass ? "Pass" : status;
      return `
        <div class="sophia-qc-row">
          <div class="sophia-qc-row-name">
            <div class="sophia-qc-row-label">${escapeHtml(label)}</div>
          </div>
          <span class="sophia-badge ${cls}">${pill}</span>
          <div class="sophia-qc-row-value">
            <div class="sophia-qc-num ${isFail ? "sophia-fail" : ""}">${escapeHtml(fmtQcValue(ind.value))}</div>
            <div class="sophia-qc-range">${escapeHtml(fmtQcRange(ind.range_lower, ind.range_upper))}</div>
          </div>
        </div>
      `;
    })
    .join("");
}

function renderQcFailCard(envelope) {
  const inds = envelope.qc_indicators || [];
  const failedCount = inds.filter((i) => (i.status || "").toUpperCase().startsWith("FAIL")).length;
  const total = inds.length;
  return `
    <div class="sophia-card-eyebrow">
      <span class="sophia-eyebrow">SOPHiA AI · Triage</span>
      <span class="sophia-badges">
        <span class="sophia-badge sophia-priority-HIGH">QC FAIL</span>
      </span>
    </div>
    <div class="sophia-headline">${formatClassifications("Quality control failed (" + failedCount + "/" + total + " indicators) — review before interpretation.")}</div>
    <div class="sophia-qc-grid">${renderQcIndicatorRows(inds)}</div>
  `;
}

// Bullets that just restate UI-visible facts. Drop them at render time.
const REDUNDANT_BULLET_PATTERNS = [
  /^all qc indicators (passed|pass)\b/i,
  /^germline (experiment|sequencing|testing)/i,
  /^somatic (experiment|sequencing|testing)/i,
  /sophia ddm hereditary cancer solution/i,
  /\bpanel\b.*\bv2\b/i,
];

function isRedundantBullet(b) {
  const t = (b || "").trim();
  if (!t) return true;
  return REDUNDANT_BULLET_PATTERNS.some((re) => re.test(t));
}

function renderVariantCard(envelope) {
  const summary = envelope.summary || envelope;
  const slots = Array.isArray(summary.bullets) ? summary.bullets : [];
  const verifyBySlot = {};
  for (const v of envelope.verification || []) {
    verifyBySlot[v.slot] = v;
  }
  const bullets = slots
    .map((b) => (typeof b === "string" ? { text: b, slot: "legacy", auto_generated: false } : b))
    .filter((b) => b.text && !isRedundantBullet(b.text))
    .map((b) => {
      const cls = b.auto_generated ? "sophia-bullet-templated" : "sophia-bullet-llm";
      const slotAttr = b.slot ? ` data-slot="${escapeHtml(b.slot)}"` : "";
      const sgAttr = b.cites_sg_id ? ` data-sg-id="${escapeHtml(b.cites_sg_id)}"` : "";
      const verify = verifyBySlot[b.slot];
      let chip = "";
      if (b.auto_generated) {
        chip = `<span class="sophia-verify sophia-verify-templated" title="Templated from variant evidence (no LLM)">T</span>`;
      } else if (verify) {
        if (verify.verified) {
          chip = `<span class="sophia-verify sophia-verify-pass" title="${verify.total_tokens} value tokens verified against cited evidence">✓</span>`;
        } else {
          const tokensList = (verify.unverified_tokens || []).join(", ");
          chip = `<span class="sophia-verify sophia-verify-fail" title="Unverified token(s): ${escapeHtml(tokensList)}">!</span>`;
        }
      }
      return `<li class="${cls}"${slotAttr}${sgAttr}>${chip}${formatClassifications(b.text)}</li>`;
    })
    .join("");
  const qcFailed = (summary.qc_status || "").toUpperCase() === "FAIL";
  const qcBadge = qcFailed
    ? `<span class="sophia-badge sophia-qc-FAILED">QC FAILED</span>`
    : "";
  return `
    <div class="sophia-card-eyebrow">
      <span class="sophia-eyebrow">SOPHiA AI · Triage</span>
      <span class="sophia-badges">
        ${qcBadge}
        <span class="sophia-badge sophia-priority-${summary.priority}">${summary.priority}</span>
      </span>
    </div>
    <div class="sophia-headline">${formatClassifications(summary.headline)}</div>
    <ul class="sophia-bullets">${bullets}</ul>
  `;
}

function renderCard(envelope, { loading = false, error = null } = {}) {
  if (loading) {
    return `
      <div class="sophia-card-eyebrow"><span class="sophia-eyebrow">SOPHiA AI · Triage</span></div>
      <div class="sophia-headline">Generating AI summary…</div>
      <div class="sophia-skeleton"></div>
      <div class="sophia-skeleton"></div>
      <div class="sophia-skeleton" style="width: 60%"></div>
    `;
  }
  if (error) {
    return `
      <div class="sophia-card-eyebrow"><span class="sophia-eyebrow">SOPHiA AI · Triage</span></div>
      <div class="sophia-headline">Could not generate summary</div>
      <div class="sophia-error-msg">${escapeHtml(error)}</div>
    `;
  }
  return renderVariantCard(envelope);
}

function ensureCardElement(panel, beforeNode) {
  let card = panel.querySelector(`#${PANEL_CARD_ID}`);
  if (!card) {
    card = document.createElement("div");
    card.id = PANEL_CARD_ID;
    card.className = "sophia-card";
    if (beforeNode && beforeNode.parentNode) {
      beforeNode.parentNode.insertBefore(card, beforeNode);
    } else {
      panel.insertBefore(card, panel.firstChild);
    }
  }
  return card;
}

function applyPriorityClass(card, envelope) {
  card.className = "sophia-card";
  const summary = envelope?.summary || envelope || {};
  const qcStatus = (summary.qc_status || "").toUpperCase();
  card.classList.add(`sophia-priority-${summary.priority || "MEDIUM"}`);
  if (qcStatus === "FAIL") card.classList.add("sophia-qc-degraded");
}

// (Native QC warning chips and the Quality indicators row are kept as-is —
// they're useful Gen2 affordances. Our card sits alongside them rather
// than replacing them.)

// Make the side panel's primary action button always visible. The panel
// lives inside a MUI Drawer that has its own `transform`, which makes
// `position: fixed` resolve against the drawer, not the viewport. To
// dodge that quirk we proxy: read the button's text + click handler and
// render a *floating clone* anchored to `document.body`, which has no
// containing-block ancestors. Clicks on the clone fire on the original.
// (Floating-clone of the side-panel action button removed — it was
// solving a Playwright-Chromium-only viewport quirk that doesn't exist
// in real Chrome, and would just overlay the native button there.)

async function renderForPanel(panel) {
  const found = findSampleNameInPanel(panel);
  if (!found) {
    if (allRuns) {
      for (const r of allRuns) await loadRunSamples(r.id);
    }
    return;
  }
  const sample = samplesByUserRef[found.userRef];
  if (!sample) return;

  const beforeNode = findInjectionPoint(panel) || panel.firstChild;
  const card = ensureCardElement(panel, beforeNode);
  card.dataset.sampleId = String(sample.id);
  const cached = summariesBySampleId[sample.id];
  if (cached) {
    applyPriorityClass(card, cached);
    card.innerHTML = renderCard(cached);
    ensureChatPanel(panel, card, sample.id, /*ready=*/ true);
    return;
  }
  card.classList.add("sophia-loading");
  card.innerHTML = renderCard(null, { loading: true });
  // Chat panel rendered immediately but disabled until the summary lands —
  // pathologist sees it spawning, so the affordance is obvious from the start.
  ensureChatPanel(panel, card, sample.id, /*ready=*/ false);
  try {
    const env = await fetchSampleSummary(sample.id);
    if (card.dataset.sampleId === String(sample.id)) {
      applyPriorityClass(card, env);
      card.innerHTML = renderCard(env);
      ensureChatPanel(panel, card, sample.id, /*ready=*/ true);
    }
  } catch (e) {
    if (card.dataset.sampleId === String(sample.id)) {
      card.classList.remove("sophia-loading");
      card.innerHTML = renderCard(null, { error: e.message || String(e) });
    }
  }
}

// ---- Chat panel ----

function ensureChatPanel(panel, anchorCard, sampleId, ready) {
  let chat = panel.querySelector(`#${PANEL_CHAT_ID}`);
  const sidStr = String(sampleId);
  if (!chat) {
    chat = document.createElement("div");
    chat.id = PANEL_CHAT_ID;
    chat.className = "sophia-chat";
    if (anchorCard && anchorCard.parentNode) {
      anchorCard.parentNode.insertBefore(chat, anchorCard.nextSibling);
    } else {
      panel.appendChild(chat);
    }
    chat.dataset.sampleId = sidStr;
    initChatPanel(chat, sampleId);
  } else if (chat.dataset.sampleId !== sidStr) {
    // Sample changed — reset DOM and re-bind handlers for the new sample.
    chat.dataset.sampleId = sidStr;
    initChatPanel(chat, sampleId);
  }
  setChatReady(chat, ready);
  renderChatMessages(chat, sampleId);
  return chat;
}

function initChatPanel(container, sampleId) {
  container.innerHTML = `
    <div class="sophia-chat-eyebrow">
      <span class="sophia-eyebrow">SOPHiA AI · Chat</span>
      <span class="sophia-chat-disclaimer">Verify clinical claims independently.</span>
    </div>
    <div class="sophia-chat-messages"></div>
    <form class="sophia-chat-form">
      <textarea
        class="sophia-chat-input"
        rows="2"
        placeholder="Ask about this case…"
        spellcheck="false"
      ></textarea>
      <button type="submit" class="sophia-chat-send">Send</button>
    </form>
  `;
  const form = container.querySelector(".sophia-chat-form");
  const input = container.querySelector(".sophia-chat-input");
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    submitChat(container, sampleId);
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submitChat(container, sampleId);
    }
  });
}

function setChatReady(container, ready) {
  const input = container.querySelector(".sophia-chat-input");
  const btn = container.querySelector(".sophia-chat-send");
  // Loading-during-request state has its own class; don't overwrite it.
  if (container.classList.contains("sophia-chat-pending")) return;
  if (input) {
    input.disabled = !ready;
    input.placeholder = ready
      ? "Ask about this case…"
      : "Generating triage summary…";
  }
  if (btn) btn.disabled = !ready;
}

async function submitChat(container, sampleId) {
  const input = container.querySelector(".sophia-chat-input");
  if (!input || input.disabled) return;
  const text = (input.value || "").trim();
  if (!text) return;
  const history = (chatBySampleId[sampleId] = chatBySampleId[sampleId] || []);
  history.push({ role: "user", content: text });
  input.value = "";
  container.classList.add("sophia-chat-pending");
  const btn = container.querySelector(".sophia-chat-send");
  if (btn) btn.disabled = true;
  input.disabled = true;
  renderChatMessages(container, sampleId);
  try {
    const resp = await bgFetch(`${BACKEND}/api/sample-chat/${sampleId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: history }),
    });
    history.push({ role: "assistant", content: resp.reply || "(empty reply)" });
  } catch (err) {
    history.push({
      role: "assistant",
      content: `(error: ${err && err.message ? err.message : String(err)})`,
      error: true,
    });
  } finally {
    container.classList.remove("sophia-chat-pending");
    if (btn) btn.disabled = false;
    input.disabled = false;
    renderChatMessages(container, sampleId);
    input.focus();
  }
}

function renderChatMessages(container, sampleId) {
  const msgsEl = container.querySelector(".sophia-chat-messages");
  if (!msgsEl) return;
  const history = chatBySampleId[sampleId] || [];
  const isPending = container.classList.contains("sophia-chat-pending");
  const items = history.map((m) => {
    const cls =
      "sophia-chat-msg sophia-chat-msg-" +
      m.role +
      (m.error ? " sophia-chat-msg-error" : "");
    return `<div class="${cls}"><div class="sophia-chat-bubble">${escapeHtml(m.content)}</div></div>`;
  });
  if (isPending) {
    items.push(
      `<div class="sophia-chat-msg sophia-chat-msg-assistant">
         <div class="sophia-chat-bubble sophia-chat-typing">
           <span></span><span></span><span></span>
         </div>
       </div>`
    );
  }
  msgsEl.innerHTML = items.join("");
  msgsEl.scrollTop = msgsEl.scrollHeight;
}

function detectExpandedRunsForPrewarm() {
  if (!allRuns) return;
  const visibleRunIds = new Set();
  for (const ref of Object.keys(samplesByUserRef)) {
    if (!document.body.innerText.includes(ref)) continue;
    const runId = samplesByUserRef[ref].ngs_run_id;
    if (runId) visibleRunIds.add(runId);
  }
  for (const id of visibleRunIds) prewarmRun(id);
}

// ---- inline row badges ----

function renderInlineBadges(envelope) {
  const summary = envelope?.summary || {};
  const qcStatus = (summary.qc_status || "").toUpperCase();
  const degraded = qcStatus === "FAIL" ? " sophia-inline-degraded" : "";
  const qcBadge = qcStatus === "FAIL"
    ? `<span class="sophia-badge sophia-qc-FAILED">QC FAILED</span>`
    : "";
  return `
    <span class="sophia-inline-badges${degraded}" data-sophia-row-badges="1">
      ${qcBadge}
      <span class="sophia-badge sophia-priority-${summary.priority}">${escapeHtml(summary.priority)}</span>
    </span>
  `;
}

function findRunSampleRows() {
  // For each known userRef, find the leaf element whose innerText is
  // EXACTLY the userRef (the Name cell's text node), then walk up to the
  // nearest [role=cell] or [class*=cell] container so our badges land in
  // the Name column rather than off-screen at the row's far right.
  const out = [];
  const seen = new Set();
  const refs = Object.keys(samplesByUserRef).sort((a, b) => b.length - a.length);
  if (!refs.length) return out;

  for (const ref of refs) {
    const candidates = document.querySelectorAll("span, p, div, h5, h6");
    // Collect all candidates for this userRef, pick the topmost VISIBLE one.
    const matches = [];
    for (const el of candidates) {
      const t = (el.innerText || "").trim();
      if (t !== ref) continue;
      if (el.offsetHeight > 80) continue;
      // Only badge inside a table row (run-expanded list). Skip matches in
      // headings / side panel titles / other contexts.
      if (!el.closest('[role="row"]')) continue;
      const r = el.getBoundingClientRect();
      const inView =
        r.width > 0 && r.height > 0 &&
        r.bottom > 0 && r.top < window.innerHeight;
      if (!inView) continue;
      matches.push({ el, top: r.top });
    }
    if (!matches.length) continue;
    // Topmost first.
    matches.sort((a, b) => a.top - b.top);
    const leaf = matches[0].el;
    // Walk up to the nearest cell-like container.
    let host = leaf;
    for (let i = 0; i < 4 && host && host.parentElement; i++) {
      host = host.parentElement;
      const role = host.getAttribute("role") || "";
      const cls = (host.className || "").toString();
      if (role === "cell" || /cell/i.test(cls) || host.offsetHeight > 80) break;
    }
    const found =
      host && host.offsetHeight <= 80 && (host.innerText || "").length < 200
        ? host
        : leaf;
    if (!seen.has(found)) {
      seen.add(found);
      out.push({ el: found, userRef: ref });
    }
  }
  return out;
}

// Visual order for the expanded run rows: HIGH first, then MEDIUM, then LOW,
// then QC-FAILED at the bottom. Samples we haven't summarised yet keep the
// default flex order (0, alongside the run-header rows above).
function sortRowsByPriority() {
  const refs = Object.keys(samplesByUserRef);
  if (!refs.length) return;
  for (const row of document.querySelectorAll('[role="row"]')) {
    const t = (row.innerText || "").trim();
    const matched = refs.find((ref) =>
      t === ref || t.startsWith(ref + "\n") || t.startsWith(ref + " ")
    );
    if (!matched) continue;
    const sample = samplesByUserRef[matched];
    if (!sample) continue;
    const env = summariesBySampleId[sample.id];
    if (!env) {
      // No summary yet — drop to the bottom so already-summarised cases lead.
      row.style.order = "5";
      continue;
    }
    const summary = env.summary || env;
    const qcStatus = (summary.qc_status || "").toUpperCase();
    let order;
    if (qcStatus === "FAIL") order = 4;
    else if (summary.priority === "HIGH") order = 1;
    else if (summary.priority === "MEDIUM") order = 2;
    else order = 3;
    row.style.order = String(order);
  }
}

function injectRowBadges() {
  // SPA may re-render rows, dropping our injected badges. Each tick:
  //   - For every found row, ensure it has exactly one .sophia-inline-badges
  //     child. If already present, skip (no DOM mutation, no observer loop).
  //   - If the row's badges are stale (different content), replace.
  const rows = findRunSampleRows();
  for (const { el, userRef } of rows) {
    const sample = samplesByUserRef[userRef];
    if (!sample) continue;
    const env = summariesBySampleId[sample.id];
    if (!env) {
      fetchSampleSummary(sample.id).then(() => scheduleTick(50)).catch(() => {});
      continue;
    }
    const wantHtml = renderInlineBadges(env).trim();
    const existing = el.querySelector(":scope > .sophia-inline-badges");
    if (existing && existing.outerHTML.trim() === wantHtml) continue;
    if (existing) existing.remove();
    const wrap = document.createElement("span");
    wrap.innerHTML = wantHtml;
    // Ensure the host cell anchors the absolute-positioned badges.
    const cs = getComputedStyle(el);
    if (cs.position === "static") el.style.position = "relative";
    el.appendChild(wrap.firstElementChild);
  }
}

// ---- Main loop ----

let timer = null;
let lastPanelKey = null;

function scheduleTick(delayMs = 80) {
  if (timer) clearTimeout(timer);
  timer = setTimeout(tick, delayMs);
}

async function tick() {
  await loadRuns();
  if (!allRuns) {
    console.log("[SOPHiA] tick: no runs yet");
    return;
  }
  for (const r of allRuns) {
    if (!Object.values(samplesByUserRef).some((s) => s.ngs_run_id === r.id)) {
      await loadRunSamples(r.id);
    }
  }
  detectExpandedRunsForPrewarm();
  injectRowBadges();
  sortRowsByPriority();

  const panel = findPanel();
  if (!panel) {
    lastPanelKey = null;
    return;
  }
  const sampleHeading = findSampleNameInPanel(panel);
  console.log(
    "[SOPHiA] tick: panel found, w=" + panel.offsetWidth +
    " sampleHeading=" + (sampleHeading ? sampleHeading.userRef : "null") +
    " known refs=" + Object.keys(samplesByUserRef).length
  );
  const key = sampleHeading ? sampleHeading.userRef : panel.outerHTML.length;
  if (key === lastPanelKey) return;
  lastPanelKey = key;
  renderForPanel(panel);
}

const observer = new MutationObserver(() => scheduleTick(80));
observer.observe(document.body, { childList: true, subtree: true });

// Direct click listener: when the pathologist clicks a sample row, kick off
// renders immediately at staggered intervals so the card appears on-screen
// the moment the SPA mounts the side panel (40-300ms typically).
document.addEventListener(
  "click",
  (e) => {
    const target = e.target instanceof Element ? e.target : null;
    if (!target) return;
    const row = target.closest('[role="row"]');
    if (!row) return;
    // Heuristic: any row whose text mentions a known sample userRef.
    const text = (row.innerText || "").trim();
    const refs = Object.keys(samplesByUserRef);
    if (!refs.some((r) => text.includes(r))) return;
    // Fire several quick ticks to catch the panel as it mounts.
    scheduleTick(0);
    setTimeout(tick, 80);
    setTimeout(tick, 200);
  },
  true
);

tick();
console.log("[SOPHiA AI Triage] side-panel mode loaded");
