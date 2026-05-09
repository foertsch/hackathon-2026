// Generate a self-contained HTML report showing example MESSi responses,
// the resulting chronotype, and a recommended weekly schedule.
//
// Usage: node generate_example_report.mjs > example_morning_week.html
// Then convert to PDF with headless Chrome.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import {
  ITEMS,
  scoreMESSi,
  alertnessCurve,
  alertnessAt,
  schedule,
  TASKS,
} from "./messi.mjs";

const __dirname = dirname(fileURLToPath(import.meta.url));

// 1. Example responses — strong morning-type pathologist ---------------------
//
// MA items (1..4 forward, 5 reversed) all maxed for "morning peak":
//   1 Very easy, 2 Very alert, 3 0–10 min, 4 Very high, 5 Fully disagree (drowsy)
// EV items (6..10 forward) all minimum for "low evening preference":
// DI items (11–12 forward, 13–15 reversed) middling for "average amplitude":
const EXAMPLE_NAME = "Sample Pathologist";
const EXAMPLE_RESPONSES = {
  1: 5, 2: 5, 3: 5, 4: 5, 5: 1,    // MA
  6: 1, 7: 1, 8: 1, 9: 1, 10: 1,   // EV
  11: 3, 12: 3, 13: 3, 14: 3, 15: 3, // DI
};

const result = scoreMESSi(EXAMPLE_RESPONSES);

// 2. Sample week from synthetic_caseloads.json (Typical Monday + 4 more days) -
const caseloads = JSON.parse(
  readFileSync(join(__dirname, "synthetic_caseloads.json"), "utf-8"),
);
const monday = caseloads.days.find((d) => d.id === "monday_typical");

// Build a Mon..Fri week. For demo, reuse Monday's caseload for all 5 days
// with slight per-day variations so the schedule isn't identical.
const dayLabels = ["Mon", "Tue", "Wed", "Thu", "Fri"];
const weekDays = dayLabels.map((label, i) => {
  let cases = monday.cases.map((c) => ({ ...c, id: `${label.toLowerCase()}-${c.id}` }));
  // Day-specific variations
  if (i === 1) cases = cases.filter((c) => c.taskType !== "departmental_meetings"); // Tue: skip meetings
  if (i === 2) cases.push({ id: "wed-extra", taskType: "departmental_meetings", durationMin: 60, urgency: 0.3 }); // Wed: extra meeting
  if (i === 3) cases = cases.filter((c) => !c.id.endsWith("M2")); // Thu: skip a microscopy
  if (i === 4) {
    cases = cases.filter((c) => c.taskType !== "tissue_assessment_fish");
    cases.push({ id: "fri-extra", taskType: "emails", durationMin: 60, urgency: 0.0 });
  }
  return { label, cases };
});

// Schedule each day independently
const weekSchedule = weekDays.map(({ label, cases }) => ({
  label,
  schedule: schedule(cases, result.z, { mode: "chronotype" }),
}));

// 3. Build SVG components -----------------------------------------------------

// Alertness curve as horizontal SVG, full width
function alertnessSVG(width = 720, height = 160) {
  const startHour = 6, endHour = 20;
  const padX = 32, padY = 24;
  const innerW = width - padX * 2;
  const innerH = height - padY * 2;
  const curve = alertnessCurve(result.z, { startHour, endHour, stepMin: 30 });
  const yMax = 2.5, yMin = -2.5;
  const x = (h) => padX + ((h - startHour) / (endHour - startHour)) * innerW;
  const y = (a) => padY + ((yMax - a) / (yMax - yMin)) * innerH;

  // Path through points
  const pts = curve.map((p) => `${x(p.hour).toFixed(1)},${y(p.alertness).toFixed(1)}`);
  const linePath = `M ${pts.join(" L ")}`;
  // Filled area down to neutral (y=0)
  const yZero = y(0);
  const areaPath = `${linePath} L ${x(endHour)},${yZero} L ${x(startHour)},${yZero} Z`;

  // Hour ticks
  const ticks = [];
  for (let h = startHour; h <= endHour; h += 2) {
    ticks.push(
      `<line x1="${x(h)}" y1="${padY + innerH}" x2="${x(h)}" y2="${padY + innerH + 4}" stroke="#9CA3AF" stroke-width="1"/>` +
      `<text x="${x(h)}" y="${padY + innerH + 16}" font-size="10" fill="#6B7280" text-anchor="middle">${String(h).padStart(2, "0")}:00</text>`,
    );
  }

  // Peak / trough markers
  let peak = curve[0], trough = curve[0];
  for (const p of curve) {
    if (p.alertness > peak.alertness) peak = p;
    if (p.alertness < trough.alertness) trough = p;
  }

  return `
<svg viewBox="0 0 ${width} ${height}" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto">
  <defs>
    <linearGradient id="alertness-grad" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#F97316" stop-opacity="0.85"/>
      <stop offset="50%" stop-color="#A855F7" stop-opacity="0.55"/>
      <stop offset="100%" stop-color="#312E81" stop-opacity="0.4"/>
    </linearGradient>
  </defs>
  <line x1="${padX}" y1="${yZero}" x2="${padX + innerW}" y2="${yZero}" stroke="#9CA3AF" stroke-width="0.6" stroke-dasharray="3,3"/>
  <text x="${padX + innerW + 4}" y="${yZero + 3}" font-size="9" fill="#9CA3AF">Pop. avg</text>
  <path d="${areaPath}" fill="url(#alertness-grad)"/>
  <path d="${linePath}" fill="none" stroke="#7C3AED" stroke-width="2"/>
  <text x="${x(peak.hour)}" y="${y(peak.alertness) - 8}" font-size="14" text-anchor="middle">🤩</text>
  <text x="${x(trough.hour)}" y="${y(trough.alertness) + 16}" font-size="14" text-anchor="middle">🥱</text>
  <text x="${padX + innerW}" y="${padY + 10}" font-size="9" fill="#6B7280" text-anchor="end">High</text>
  <text x="${padX + innerW}" y="${padY + innerH - 2}" font-size="9" fill="#6B7280" text-anchor="end">Low</text>
  ${ticks.join("\n  ")}
</svg>`;
}

// Vertical day column for the weekly grid
function dayColumnSVG({ label, schedule: daySched }, colWidth = 160, height = 480) {
  const startHour = 6, endHour = 20;
  const padX = 30, padY = 28;
  const innerH = height - padY * 2;
  const innerW = colWidth - padX - 6;
  const y = (h) => padY + ((h - startHour) / (endHour - startHour)) * innerH;

  // 2-hour gridlines
  const gridlines = [];
  for (let h = startHour; h <= endHour; h += 2) {
    gridlines.push(
      `<line x1="0" y1="${y(h)}" x2="${colWidth}" y2="${y(h)}" stroke="#E5E7EB" stroke-width="0.6"/>` +
      `<text x="2" y="${y(h) + 3}" font-size="9" fill="#6B7280">${String(h).padStart(2, "0")}:00</text>`,
    );
  }

  // Rationale color per block based on mean alertness
  const allAlert = daySched.scheduled.map((s) => s.meanAlertness);
  const aMax = Math.max(...allAlert, 0.1);
  function colorFor(s) {
    if (s.urgency >= 0.9) return { fill: "#FEE2E2", stroke: "#DC2626" };
    const ratio = s.meanAlertness / aMax;
    if (ratio > 0.7) return { fill: "#FED7AA", stroke: "#EA580C" }; // peak
    if (ratio > 0.4) return { fill: "#FEF3C7", stroke: "#D97706" }; // best avail
    if (ratio > 0.0) return { fill: "#DDD6FE", stroke: "#7C3AED" }; // moderate
    return { fill: "#E2E8F0", stroke: "#475569" }; // low
  }

  const blocks = daySched.scheduled.map((s) => {
    const yTop = y(s.startHour);
    const yBot = y(s.endHour);
    const h = yBot - yTop;
    const c = colorFor(s);
    const label = TASKS[s.taskType]?.label ?? s.taskType;
    const stat = s.urgency >= 0.9 ? `<text x="${padX + 4}" y="${yTop + 12}" font-size="11" fill="#DC2626" font-weight="bold">!</text>` : "";
    return `
  <rect x="${padX}" y="${yTop}" width="${innerW}" height="${h}" fill="${c.fill}" stroke="${c.stroke}" stroke-width="1" rx="3"/>
  ${stat}
  <text x="${padX + (s.urgency >= 0.9 ? 14 : 4)}" y="${yTop + 12}" font-size="9" fill="#1f2937" font-weight="600">${label}</text>
  <text x="${padX + (s.urgency >= 0.9 ? 14 : 4)}" y="${yTop + 22}" font-size="8" fill="#6B7280">${s.durationMin}min · ${s.startLabel}</text>`;
  }).join("");

  return `
<svg viewBox="0 0 ${colWidth} ${height}" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto;display:block">
  <text x="${colWidth / 2}" y="14" font-size="11" font-weight="bold" fill="#0F766E" text-anchor="middle">${label}</text>
  ${gridlines.join("\n  ")}
  ${blocks}
</svg>`;
}

// 4. Build the HTML report ----------------------------------------------------

function escape(s) {
  return String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]);
}

const responsesTable = ITEMS.map((it) => {
  const raw = EXAMPLE_RESPONSES[it.id];
  const scored = it.reverse ? 6 - raw : raw;
  return `<tr>
    <td>${it.id}</td>
    <td>${escape(it.subscale)}</td>
    <td>${escape(it.text)}</td>
    <td style="text-align:center">${raw}</td>
    <td style="text-align:center;color:#6B7280">${it.reverse ? `(rev → ${scored})` : ""}</td>
  </tr>`;
}).join("\n");

const orderRationale = weekSchedule.map(({ label, schedule: ds }) => {
  const rows = ds.scheduled.map((s) => {
    const taskLabel = TASKS[s.taskType]?.label ?? s.taskType;
    let rationale;
    const aMax = Math.max(...ds.scheduled.map((x) => x.meanAlertness), 0.1);
    const ratio = s.meanAlertness / aMax;
    if (s.urgency >= 0.9) rationale = "STAT — locked to earliest free slot";
    else if (s.cogLoad >= 0.7 && ratio > 0.7) rationale = "your peak focus window";
    else if (s.cogLoad >= 0.7) rationale = "best available focus window today";
    else if (s.cogLoad >= 0.4) rationale = "moderate-focus slot";
    else rationale = "low-focus slot — saves your peak hours for harder work";
    return `<tr><td>${s.startLabel}</td><td><b>${escape(taskLabel)}</b></td><td>${s.durationMin}min</td><td style="color:#6B7280">${rationale}</td></tr>`;
  }).join("");
  return `<h4 style="margin:12px 0 4px;color:#0F766E">${label}</h4>
<table class="rationale"><tbody>${rows}</tbody></table>`;
}).join("");

const html = `<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>PathoChrono — Example weekly report</title>
<style>
  @page { size: A4 landscape; margin: 14mm; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif; color:#111827; background:#FAFAF8; margin:0; }
  h1 { font-size: 22px; margin: 0 0 4px; }
  h2 { font-size: 14px; margin: 16px 0 6px; color:#0F766E; text-transform: uppercase; letter-spacing:0.04em; }
  h4 { font-size: 11px; }
  .header { padding: 14px 18px; background: #fff; border-radius: 8px; border:1px solid #E5E7EB; }
  .scores { color:#6B7280; font-size:11px; letter-spacing:0.05em; text-transform:uppercase; margin-top:4px; }
  .types { font-size:13px; margin-top:2px; }
  .types .match { font-weight:bold; color:#0F766E; }
  .types .other { color:#9CA3AF; }
  .legend { font-size:10px; color:#6B7280; margin: 8px 0 4px; }
  .legend span { display:inline-block; margin-right:14px; }
  .legend .swatch { display:inline-block; width:10px; height:10px; border-radius:2px; vertical-align:middle; margin-right:4px; }
  .week-grid { display:grid; grid-template-columns: repeat(5, 1fr); gap: 8px; margin-top: 8px; }
  table { border-collapse: collapse; width:100%; font-size:11px; }
  table th, table td { text-align:left; padding: 4px 8px; border-bottom: 1px solid #F3F4F6; }
  table th { color:#6B7280; font-weight:600; text-transform:uppercase; font-size:10px; letter-spacing:0.05em; }
  table.rationale td { font-size:10px; padding: 2px 6px; }
  .footnote { font-size:9px; color:#9CA3AF; margin-top: 14px; border-top: 1px solid #F3F4F6; padding-top: 8px; }
  .col-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  .responses-table { font-size: 9px; }
  .responses-table td, .responses-table th { padding: 2px 4px; }
  .page-break { page-break-after: always; }
</style>
</head>
<body>
  <div class="header">
    <h1>${escape(EXAMPLE_NAME)}</h1>
    <div class="scores">MA ${result.MA} · EV ${result.EV} · DI ${result.DI}</div>
    <div class="types">
      <span class="${result.chronotype === "morning" ? "match" : "other"}">Morning</span>
      <span class="other"> · </span>
      <span class="${result.chronotype === "intermediate" ? "match" : "other"}">Intermediate</span>
      <span class="other"> · </span>
      <span class="${result.chronotype === "evening" ? "match" : "other"}">Evening</span>
    </div>
    <div class="scores" style="margin-top:6px">chronotype mode · Mon–Fri · 06:00–20:00 · example weekly run · generated ${new Date().toISOString().slice(0, 10)}</div>
  </div>

  <h2>Alertness</h2>
  ${alertnessSVG()}

  <div class="legend">
    <span><span class="swatch" style="background:#EA580C"></span>Peak focus</span>
    <span><span class="swatch" style="background:#D97706"></span>Best available</span>
    <span><span class="swatch" style="background:#7C3AED"></span>Moderate</span>
    <span><span class="swatch" style="background:#475569"></span>Low focus</span>
    <span><span class="swatch" style="background:#DC2626"></span>STAT</span>
  </div>

  <h2>Recommended weekly schedule</h2>
  <div class="week-grid">
    ${weekSchedule.map((d) => dayColumnSVG(d)).join("\n    ")}
  </div>

  <div class="page-break"></div>

  <h2>Order &amp; rationale</h2>
  ${orderRationale}

  <h2>Example questionnaire responses</h2>
  <table class="responses-table">
    <thead><tr><th>#</th><th>Subscale</th><th>Item</th><th>Raw</th><th>Scored</th></tr></thead>
    <tbody>${responsesTable}</tbody>
  </table>

  <div class="footnote">
    Generated by PathoChrono. Scoring per Randler, Díaz-Morales, Rahafar &amp; Vollmer (2016), <i>Chronobiology International</i> 33(7):832–848 (MESSi). Alertness model derived from Table 10 of the same paper. German norms (n=2096) per Vagos et al. 2019, <i>Front. Psychol.</i> Example responses are fictional; not real patient data.
  </div>
</body>
</html>`;

process.stdout.write(html);
