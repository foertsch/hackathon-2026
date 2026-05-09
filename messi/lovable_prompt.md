# Lovable build prompt — Chronotype-aware Pathologist Scheduler

Paste **the entire section between the `--- BEGIN ---` and `--- END ---` markers** into Lovable as your initial prompt. After Lovable scaffolds the app, also paste the contents of `messi.mjs` and `synthetic_caseloads.json` (in that order) into the chat as follow-up messages so Lovable has the exact logic and data.

---

--- BEGIN ---

Build a single-page web app called **"PathoChrono"** that recommends a daily case-order schedule to a genomic pathologist based on their chronotype (measured by the MESSi questionnaire).

## Goal in one sentence
Given a pathologist's MESSi answers and today's caseload, output a 06:00–20:00 schedule that places high-cognitive-load cases in their personal alertness peak and low-load tasks in their trough — with three switchable modes — so the pathologist finishes correct work faster.

## Three screens (in this order)

### Screen 1 — MESSi questionnaire
- Title: "How does your day work?" Subtitle: "15 quick questions. ~3 minutes."
- Render the 15 items from `ITEMS` (in `messi.mjs`) as a single scrollable form.
- Each item is a 5-button radio row showing the item's `anchors[0..4]` mapped to scores 1..5. Show the item text, hide the source code (e.g. "CCQ4") in a small caption below.
- A faint subscale label ("Morning Affect" / "Eveningness" / "Distinctness") above each group.
- "Continue" button at the bottom, disabled until all 15 are answered.
- On submit: call `scoreMESSi(responses)` → keep `{MA, EV, DI, z, chronotype}` in app state, then route to Screen 2.
- Show a small chronotype banner at the top of Screen 2/3: e.g. "Morning type · MA 21 · EV 8 · DI 14".

### Screen 2 — Caseload
- Title: "Today's caseload"
- Tab 1 — **Sample day**: dropdown of the 5 days from `synthetic_caseloads.json`. Selecting one fills the table.
- Tab 2 — **Custom**: the user can add/remove cases. Each row: task type (dropdown of the 7 keys in `TASKS`, showing label), duration (15-min steps, default 60), urgency (slider 0–1 with anchors "routine / priority / STAT" at 0 / 0.5 / 1).
- Mode selector (segmented control, top right):
  - "Chronotype" (default)
  - "Urgency-respecting"
  - "Stability-aware"
- "See schedule" button → Screen 3.

### Screen 3 — Schedule
Three components stacked:

**(a) Alertness curve** (line chart, full width, ~120px tall)
- X axis: 06:00 to 20:00 in 30-min ticks.
- Y axis: alertness score (centered on 0; range typically −2..+2).
- Data: `alertnessCurve(z, { startHour: 6, endHour: 20, stepMin: 30, diModulation: mode === "stability" })`.
- Shade the area positive (above 0) in a warm color, negative below 0 in a cool color.
- A subtle "now" marker if you want, but optional.

**(b) Gantt schedule** (full width)
- One row per scheduled case, ordered by start time.
- Each block colored by cognitive-load tier: red (≥0.8), orange (0.6–0.8), yellow (0.4–0.6), grey (<0.4).
- Block label: case id + task label + duration. On hover: urgency, mean alertness during block.
- Empty 30-min slots between blocks should appear as light grey "free" gaps (the user's break time) — not all 14 hours are work; only 8h are scheduled.
- Time axis above the chart matching the alertness curve so they line up visually.

**(c) Ranked list with rationale**
- A vertically stacked list of the scheduled cases in start-time order.
- For each: "09:00 — Genomic interpretation (90min) — your peak focus window".
- Rationale strings:
  - cogLoad ≥ 0.7 in a high-alertness slot → "your peak focus window"
  - cogLoad ≥ 0.7 in a mid slot → "best available focus window today"
  - 0.4 ≤ cogLoad < 0.7 → "moderate-focus slot"
  - cogLoad < 0.4 → "low-focus slot — saves your peak hours for harder work"
  - urgency ≥ 0.9 → prepend "STAT — locked to earliest free slot · "
- A small footer: "Mode: <mode> · 8h scheduled · X cases skipped (over capacity)".

A "← Edit caseload" button returns to Screen 2 without losing answers.
A "← Re-take questionnaire" link in the chronotype banner returns to Screen 1.

## Logic — use the supplied module exactly
A file `messi.mjs` will be supplied next. **Do not re-implement any of its logic.** Convert it to TypeScript (`messi.ts`) but keep all values, formulas, item wording, and norms identical. The exports are:

- `ITEMS` — array of 15 items: `{ id, source, subscale, reverse, text, anchors[5] }`.
- `NORMS` — German norms `{MA, EV, DI: { mean, sd } }`.
- `scoreMESSi(responses)` — input is `{ [itemId]: 1..5 }` for ids 1..15.
- `classifyChronotype(z)` — returns `"morning" | "intermediate" | "evening"`.
- `alertnessAt(hour, z, opts)` — single-hour alertness.
- `alertnessCurve(z, opts)` — sampled curve for plotting.
- `TASKS` — 7 task types with `{ label, cogLoad }`.
- `schedule(cases, z, opts)` — scheduler. `opts.mode` is `"chronotype"` (default), `"urgency"`, or `"stability"`.

## Visual style
- Clean, clinical, calm. Off-white background (#FAFAF8). System sans-serif. Generous spacing.
- Accent color: deep teal (#0F766E).
- Cognitive-load colors: red (#DC2626), orange (#EA580C), yellow (#CA8A04), grey (#9CA3AF).
- No emojis. No animations beyond a simple fade between screens.

## Tech
- React + TypeScript + Vite (Lovable's default).
- Charts: `recharts` is fine; or plain SVG if simpler.
- No backend. All state lives in-memory; lose it on refresh.

## What NOT to do
- Don't add login, accounts, or persistence.
- Don't ask for the user's birthday, sex, age, or any PHI.
- Don't soften the rationale strings into LLM-speak — they should be direct.
- Don't change the MESSi item wording, anchors, scoring direction, or norm constants.
- Don't add a "AI explanation" feature unless you can ground every word in the supplied logic — the briefing's hard constraint is "no hallucinations on clinical content."

--- END ---

## After Lovable scaffolds:

**Message 2** — paste `messi.mjs` with the prefix:
> Here is `messi.mjs`. Convert to `messi.ts` (preserve everything: exports, item wording, norms, formulas, anchors). Use it as the only source of truth for scoring and scheduling.

**Message 3** — paste `synthetic_caseloads.json` with the prefix:
> Here is `synthetic_caseloads.json`. Use as the data source for the "Sample day" dropdown on Screen 2.

**Message 4 (only if needed)** — for visual polish:
> The Gantt blocks should align horizontally with the alertness chart so the user can see at a glance that high-load blocks sit on the curve's peak. If they don't currently align, share the same x-scale.
