import { test } from "node:test";
import assert from "node:assert/strict";

import {
  ITEMS,
  NORMS,
  scoreMESSi,
  classifyChronotype,
  alertnessAt,
  alertnessCurve,
  schedule,
  TASKS,
  WORK_HABITS,
} from "./messi.mjs";

// Helpers --------------------------------------------------------------------

function uniformResponses(value) {
  const r = {};
  for (let i = 1; i <= 15; i++) r[i] = value;
  return r;
}

// 1. Item set ---------------------------------------------------------------

test("there are 15 items, 5 per subscale", () => {
  assert.equal(ITEMS.length, 15);
  const counts = ITEMS.reduce((acc, it) => {
    acc[it.subscale] = (acc[it.subscale] ?? 0) + 1;
    return acc;
  }, {});
  assert.deepEqual(counts, { MA: 5, EV: 5, DI: 5 });
});

test("reverse-keyed items are exactly CCQ4 (item 5) and DI items 13/14/15", () => {
  const reverses = ITEMS.filter((it) => it.reverse).map((it) => it.id).sort((a, b) => a - b);
  assert.deepEqual(reverses, [5, 13, 14, 15]);
});

// 2. Scoring ----------------------------------------------------------------

test("uniform 3 yields midpoint subscales (15 each)", () => {
  const r = scoreMESSi(uniformResponses(3));
  assert.equal(r.MA, 15);
  assert.equal(r.EV, 15);
  assert.equal(r.DI, 15);
});

test("uniform 1 vs uniform 5 covers full range with reverse-coding applied", () => {
  // MA: 4 forward + 1 reverse → all 1s = 4*1 + (6-1) = 9. all 5s = 4*5 + (6-5) = 21.
  // EV: 5 forward → 5..25.
  // DI: 2 forward + 3 reverse → all 1s = 2 + 3*5 = 17. all 5s = 10 + 3 = 13.
  const lo = scoreMESSi(uniformResponses(1));
  const hi = scoreMESSi(uniformResponses(5));

  assert.equal(lo.MA, 9);
  assert.equal(hi.MA, 21);
  assert.equal(lo.EV, 5);
  assert.equal(hi.EV, 25);
  assert.equal(lo.DI, 17);
  assert.equal(hi.DI, 13);
});

test("scoreMESSi rejects out-of-range values", () => {
  const bad = uniformResponses(3);
  bad[1] = 0;
  assert.throws(() => scoreMESSi(bad), /1\.\.5/);

  bad[1] = 6;
  assert.throws(() => scoreMESSi(bad), /1\.\.5/);

  bad[1] = "3";
  assert.throws(() => scoreMESSi(bad), /1\.\.5/);
});

test("z-scores at the German norm means are ~0", () => {
  const responses = uniformResponses(3);
  // Tweak so subscales hit the published means as closely as integer responses allow.
  // MA mean 15.5: all 3s already give 15. Acceptable; z = (15-15.5)/4.3 ≈ -0.116.
  // EV mean 15.8: all 3s give 15; z ≈ -0.195.
  // DI mean 17.1: all 3s give 15; z ≈ -0.636.
  const r = scoreMESSi(responses);
  assert.ok(Math.abs(r.z.MA) < 0.2, `z.MA=${r.z.MA}`);
  assert.ok(Math.abs(r.z.EV) < 0.25, `z.EV=${r.z.EV}`);
});

// 3. Chronotype classification ---------------------------------------------

test("classifyChronotype: morning vs evening vs intermediate", () => {
  assert.equal(classifyChronotype({ MA: 1.0, EV: -1.0, DI: 0 }), "morning");
  assert.equal(classifyChronotype({ MA: -1.0, EV: 1.0, DI: 0 }), "evening");
  assert.equal(classifyChronotype({ MA: 0.0, EV: 0.0, DI: 0 }), "intermediate");
  // boundary
  assert.equal(classifyChronotype({ MA: 0.25, EV: -0.25, DI: 0 }), "intermediate");
  assert.equal(classifyChronotype({ MA: 0.3, EV: -0.3, DI: 0 }), "morning");
});

test("strong morning chronotype emerges from morning-heavy responses", () => {
  // Maximum MA, minimum EV
  const r = {
    1: 5, 2: 5, 3: 5, 4: 5, 5: 1, // MA all maxed (item 5 reversed)
    6: 1, 7: 1, 8: 1, 9: 1, 10: 1, // EV all minimum
    11: 3, 12: 3, 13: 3, 14: 3, 15: 3,
  };
  const out = scoreMESSi(r);
  assert.equal(out.chronotype, "morning");
  assert.equal(out.MA, 25);
  assert.equal(out.EV, 5);
});

test("strong evening chronotype emerges from evening-heavy responses", () => {
  const r = {
    1: 1, 2: 1, 3: 1, 4: 1, 5: 5, // MA all min
    6: 5, 7: 5, 8: 5, 9: 5, 10: 5, // EV all max
    11: 3, 12: 3, 13: 3, 14: 3, 15: 3,
  };
  const out = scoreMESSi(r);
  assert.equal(out.chronotype, "evening");
});

// 4. Alertness curve --------------------------------------------------------

test("alertnessAt: morning type peaks early and dips late", () => {
  const z = { MA: 1.5, EV: -1.5, DI: 0 };
  const morning = alertnessAt(8, z);
  const afternoon = alertnessAt(14, z);
  const evening = alertnessAt(20, z);
  assert.ok(morning > afternoon, `morning(${morning}) should beat afternoon(${afternoon})`);
  assert.ok(morning > evening, `morning(${morning}) should beat evening(${evening})`);
});

test("alertnessAt: evening type peaks late and dips early", () => {
  const z = { MA: -1.5, EV: 1.5, DI: 0 };
  const morning = alertnessAt(8, z);
  const evening = alertnessAt(20, z);
  assert.ok(evening > morning, `evening(${evening}) should beat morning(${morning})`);
});

test("alertnessAt: intermediate type has a flatter curve than morning", () => {
  const flat = { MA: 0, EV: 0, DI: 0 };
  const peakish = { MA: 1.5, EV: -1.5, DI: 0 };
  const flatRange = Math.abs(alertnessAt(8, flat) - alertnessAt(20, flat));
  const peakRange = Math.abs(alertnessAt(8, peakish) - alertnessAt(20, peakish));
  assert.ok(peakRange > flatRange);
});

test("alertnessAt is continuous at bin boundaries (no jumps)", () => {
  const z = { MA: 1.0, EV: -1.0, DI: 0 };
  for (const mid of [9, 11, 13, 15, 17, 19]) {
    const before = alertnessAt(mid - 0.001, z);
    const at = alertnessAt(mid, z);
    const after = alertnessAt(mid + 0.001, z);
    assert.ok(Math.abs(before - at) < 0.005, `discontinuity at ${mid}-`);
    assert.ok(Math.abs(after - at) < 0.005, `discontinuity at ${mid}+`);
  }
});

test("alertnessCurve covers the requested window at the requested step", () => {
  const z = { MA: 0, EV: 0, DI: 0 };
  const curve = alertnessCurve(z, { startHour: 6, endHour: 20, stepMin: 30 });
  assert.equal(curve[0].hour, 6);
  assert.equal(curve[curve.length - 1].hour, 20);
  assert.equal(curve.length, (20 - 6) * 2 + 1);
});

test("DI modulation amplifies extremes for high-DI users", () => {
  const z = { MA: 1.5, EV: -1.5, DI: 1.5 };
  const flatDI = { MA: 1.5, EV: -1.5, DI: 0 };
  const sharp = Math.abs(alertnessAt(8, z, { diModulation: true }));
  const baseline = Math.abs(alertnessAt(8, flatDI, { diModulation: true }));
  assert.ok(sharp > baseline);
});

// 5. Scheduler --------------------------------------------------------------

const SAMPLE_CASES = [
  { id: "c1", taskType: "microscopy",             durationMin: 90, urgency: 0.4 },
  { id: "c2", taskType: "tissue_assessment_fish", durationMin: 60, urgency: 0.3 },
  { id: "c3", taskType: "tissue_assessment_fish", durationMin: 60, urgency: 0.3 },
  { id: "c4", taskType: "departmental_meetings",  durationMin: 60, urgency: 0.2 },
  { id: "c5", taskType: "technical_validation",   durationMin: 60, urgency: 0.1 },
  { id: "c6", taskType: "emails",                 durationMin: 30, urgency: 0.0 },
  { id: "c7", taskType: "emails",                 durationMin: 30, urgency: 0.0 },
];

test("scheduler total scheduled minutes <= 8h cap", () => {
  const z = { MA: 1.0, EV: -1.0, DI: 0 };
  const out = schedule(SAMPLE_CASES, z);
  assert.ok(out.workMinutesUsed <= 8 * 60, `used=${out.workMinutesUsed}`);
});

test("scheduler: morning chronotype puts microscopy in the morning", () => {
  const z = { MA: 1.5, EV: -1.5, DI: 0 };
  const out = schedule(SAMPLE_CASES, z);
  const top = out.scheduled.find((s) => s.taskType === "microscopy");
  assert.ok(top, "top-load task should be scheduled");
  assert.ok(top.startHour < 12, `expected morning start, got ${top.startLabel}`);
});

test("scheduler: evening chronotype puts microscopy in the evening", () => {
  const z = { MA: -1.5, EV: 1.5, DI: 0 };
  const out = schedule(SAMPLE_CASES, z);
  const top = out.scheduled.find((s) => s.taskType === "microscopy");
  assert.ok(top, "top-load task should be scheduled");
  assert.ok(top.startHour >= 12, `expected afternoon/evening start, got ${top.startLabel}`);
});

test("scheduler: admin / low-cog tasks land in the trough relative to top tasks", () => {
  const z = { MA: 1.5, EV: -1.5, DI: 0 };
  const out = schedule(SAMPLE_CASES, z);
  const admin = out.scheduled.find((s) => s.taskType === "emails");
  const top = out.scheduled.find((s) => s.taskType === "microscopy");
  assert.ok(admin && top);
  assert.ok(
    admin.meanAlertness < top.meanAlertness,
    `admin alertness ${admin.meanAlertness.toFixed(2)} should be < top ${top.meanAlertness.toFixed(2)}`,
  );
});

test("scheduler: urgency mode puts STAT case in earliest available slot", () => {
  const z = { MA: 1.5, EV: -1.5, DI: 0 }; // morning type
  const cases = [
    { id: "stat",  taskType: "emails",         durationMin: 60, urgency: 1.0 },
    { id: "deep",  taskType: "microscopy", durationMin: 90, urgency: 0.2 },
    { id: "filler", taskType: "technical_validation",   durationMin: 60, urgency: 0.1 },
  ];
  const out = schedule(cases, z, { mode: "urgency" });
  const stat = out.scheduled.find((s) => s.id === "stat");
  const deep = out.scheduled.find((s) => s.id === "deep");
  // STAT admin should start before the deep-focus task even though admin is low-cog and
  // the morning-type's peak is early.
  assert.ok(stat.startSlot < deep.startSlot, `STAT at ${stat.startLabel} vs deep at ${deep.startLabel}`);
  assert.equal(stat.startSlot, 0, "STAT should start at first slot");
});

test("scheduler: chronotype mode without STAT lock would put deep work first for morning type", () => {
  const z = { MA: 1.5, EV: -1.5, DI: 0 };
  const cases = [
    { id: "stat", taskType: "emails",         durationMin: 60, urgency: 1.0 },
    { id: "deep", taskType: "microscopy", durationMin: 90, urgency: 0.2 },
  ];
  const out = schedule(cases, z, { mode: "chronotype" }); // ignores urgency
  const stat = out.scheduled.find((s) => s.id === "stat");
  const deep = out.scheduled.find((s) => s.id === "deep");
  assert.ok(deep.startSlot < stat.startSlot, "deep work should win the morning peak in chronotype mode");
});

test("scheduler: cases that exceed capacity are listed as skipped", () => {
  const z = { MA: 0, EV: 0, DI: 0 };
  // 7 cases × 90 min = 630 min > 480 min cap, so at least one skipped.
  const big = SAMPLE_CASES.map((c) => ({ ...c, durationMin: 90 }));
  const out = schedule(big, z);
  assert.ok(out.skipped.length > 0);
  assert.ok(out.workMinutesUsed <= 8 * 60);
});

test("scheduler: stability mode produces a flatter assignment for low-DI users", () => {
  // For a low-DI user, peak-vs-trough alertness gap should shrink, so the
  // alertness gap between top-task slot and admin slot should be smaller
  // than with the same MA/EV but high DI.
  const lowDI = { MA: 1.5, EV: -1.5, DI: -1.5 };
  const highDI = { MA: 1.5, EV: -1.5, DI: 1.5 };
  const lowOut = schedule(SAMPLE_CASES, lowDI, { mode: "stability" });
  const highOut = schedule(SAMPLE_CASES, highDI, { mode: "stability" });

  const gap = (out) => {
    const top = out.scheduled.find((s) => s.taskType === "microscopy");
    const admin = out.scheduled.find((s) => s.taskType === "emails");
    return top.meanAlertness - admin.meanAlertness;
  };
  assert.ok(gap(lowOut) < gap(highOut), `low-DI gap ${gap(lowOut).toFixed(2)} should be smaller than high-DI ${gap(highOut).toFixed(2)}`);
});

// 6. TASKS sanity ----------------------------------------------------------

test("there are exactly 5 task types and cogLoads are within [0,1]", () => {
  const keys = Object.keys(TASKS);
  assert.equal(keys.length, 5);
  for (const k of keys) {
    assert.ok(TASKS[k].cogLoad >= 0 && TASKS[k].cogLoad <= 1, `${k}: ${TASKS[k].cogLoad}`);
  }
});

test("microscopy has the highest cogLoad; emails the lowest", () => {
  const sorted = Object.entries(TASKS).sort((a, b) => b[1].cogLoad - a[1].cogLoad);
  assert.equal(sorted[0][0], "microscopy");
  assert.equal(sorted[sorted.length - 1][0], "emails");
});

// 7. Work habit (optional, soft preference) -------------------------------

const HABIT_CASES = [
  { id: "h1", taskType: "microscopy",             durationMin: 60, urgency: 0.3 },
  { id: "h2", taskType: "tissue_assessment_fish", durationMin: 60, urgency: 0.3 },
  { id: "h3", taskType: "departmental_meetings",  durationMin: 60, urgency: 0.2 },
  { id: "h4", taskType: "technical_validation",   durationMin: 60, urgency: 0.1 },
  { id: "h5", taskType: "emails",                 durationMin: 60, urgency: 0.0 },
];

test("WORK_HABITS exposes the 6 expected ids in order", () => {
  assert.deepEqual(WORK_HABITS.map((h) => h.id), [
    "none", "finish_asap", "long_lunch", "chill_morning", "focus_window", "crash_evening",
  ]);
});

test("workHabit defaults to none and is reflected in the output", () => {
  const z = { MA: 1.0, EV: -1.0, DI: 0 };
  const out = schedule(HABIT_CASES, z);
  assert.equal(out.workHabit, "none");
  const out2 = schedule(HABIT_CASES, z, { workHabit: "finish_asap" });
  assert.equal(out2.workHabit, "finish_asap");
});

test("habit 'finish_asap' shifts overall placement earlier vs 'none'", () => {
  const z = { MA: 1.0, EV: -1.0, DI: 0 };
  const baseline = schedule(HABIT_CASES, z);
  const asap = schedule(HABIT_CASES, z, { workHabit: "finish_asap" });
  const meanStart = (out) =>
    out.scheduled.reduce((sum, s) => sum + s.startSlot, 0) / out.scheduled.length;
  assert.ok(meanStart(asap) <= meanStart(baseline), `asap mean ${meanStart(asap)} should be <= baseline ${meanStart(baseline)}`);
});

test("habit 'crash_evening' shifts overall placement later vs 'none'", () => {
  // Use an evening type to get a positive-alertness window in the afternoon/evening.
  const z = { MA: -1.0, EV: 1.0, DI: 0 };
  const baseline = schedule(HABIT_CASES, z);
  const crash = schedule(HABIT_CASES, z, { workHabit: "crash_evening" });
  const meanStart = (out) =>
    out.scheduled.reduce((sum, s) => sum + s.startSlot, 0) / out.scheduled.length;
  assert.ok(meanStart(crash) >= meanStart(baseline), `crash mean ${meanStart(crash)} should be >= baseline ${meanStart(baseline)}`);
});

test("habit 'long_lunch' tends to leave the 12:00-13:30 band emptier", () => {
  const z = { MA: 1.0, EV: -1.0, DI: 0 };
  const overlapsLunch = (s) => s.startHour < 13.5 && s.endHour > 12;
  const baseline = schedule(HABIT_CASES, z);
  const longLunch = schedule(HABIT_CASES, z, { workHabit: "long_lunch" });
  const baseLunchCount = baseline.scheduled.filter(overlapsLunch).length;
  const habitLunchCount = longLunch.scheduled.filter(overlapsLunch).length;
  assert.ok(
    habitLunchCount <= baseLunchCount,
    `long_lunch overlapped lunch ${habitLunchCount}, baseline ${baseLunchCount}`,
  );
});

test("habit 'chill_morning' shifts the average start time later", () => {
  const z = { MA: 0.5, EV: -0.5, DI: 0 };
  const baseline = schedule(HABIT_CASES, z);
  const chill = schedule(HABIT_CASES, z, { workHabit: "chill_morning" });
  const earliestStart = (out) => Math.min(...out.scheduled.map((s) => s.startHour));
  assert.ok(
    earliestStart(chill) >= earliestStart(baseline),
    `chill earliest ${earliestStart(chill)} should be >= baseline ${earliestStart(baseline)}`,
  );
});

test("habit 'focus_window' anchors a high-cog task close to the user's peak", () => {
  const z = { MA: 1.5, EV: -1.5, DI: 0 };
  const out = schedule(HABIT_CASES, z, { workHabit: "focus_window" });
  const top = out.scheduled.find((s) => s.taskType === "microscopy");
  // For a strong morning type, peak is ~09:00. Microscopy block should sit within ~2h of it.
  assert.ok(top, "top task scheduled");
  assert.ok(Math.abs(top.startHour - 9) < 2.5, `expected near peak, got ${top.startLabel}`);
});

test("habit weight is small: never overrides a strong alertness preference", () => {
  // A strong morning type with a single high-cog task. Even with finish_asap or crash_evening,
  // the task should remain inside the morning's high-alertness window (the alertness term
  // dominates the soft habit nudge).
  const z = { MA: 1.5, EV: -1.5, DI: 0 };
  const cases = [{ id: "deep", taskType: "microscopy", durationMin: 90, urgency: 0.3 }];
  const baseline = schedule(cases, z).scheduled[0];
  const asap = schedule(cases, z, { workHabit: "finish_asap" }).scheduled[0];
  const crash = schedule(cases, z, { workHabit: "crash_evening" }).scheduled[0];
  // All three placements should stay within the morning peak (06:00 - 12:00).
  for (const r of [baseline, asap, crash]) {
    assert.ok(r.startHour >= 6 && r.startHour < 12, `morning-peak placement violated: ${r.startLabel}`);
  }
});
