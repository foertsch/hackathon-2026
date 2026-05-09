// MESSi (Morningness-Eveningness-Stability Scale improved) scoring,
// alertness curve, and chronotype-aware caseload scheduler.
//
// Source: Randler, Díaz-Morales, Rahafar & Vollmer (2016),
// "Morningness-eveningness and amplitude — development and validation
// of an improved composite scale to measure circadian preference and
// stability (MESSi)", Chronobiology International 33(7): 832–848.
// English item set: Appendix 8. Alertness × subscale correlations: Table 10.
// German norms (n=2096): Vagos et al. 2019, Front. Psychol.

// ---------------------------------------------------------------------------
// 1. The 15 MESSi items
// ---------------------------------------------------------------------------
//
// Each item is rated 1..5. The `reverse` flag means the raw response is
// reverse-scored before contributing to the subscale total (score = 6 - raw).
// Subscale totals are sums in the range 5..25.

export const ITEMS = [
  // Morning Affect
  { id: 1,  source: "CSM3",       subscale: "MA", reverse: false,
    text: "Assuming normal circumstance, how easy do you find getting up in the morning?",
    anchors: ["Not at all easy", "Slightly easy", "Neither easy nor uneasy", "Fairly easy", "Very easy"] },
  { id: 2,  source: "CSM4",       subscale: "MA", reverse: false,
    text: "How alert do you feel during the first half hour after having awakened in the morning?",
    anchors: ["Not at all alert", "Slightly alert", "Medium", "Fairly alert", "Very alert"] },
  { id: 3,  source: "CSM12",      subscale: "MA", reverse: false,
    text: "How long a time does it usually take before you 'recover your senses' in the morning after rising from a night's sleep?",
    anchors: ["More than 60 min", "41–60 min", "21–40 min", "11–20 min", "0–10 min"] },
  { id: 4,  source: "CIRENS1",    subscale: "MA", reverse: false,
    text: "In general, how is your energy level in the morning?",
    anchors: ["Very low", "Low", "Moderate", "High", "Very high"] },
  { id: 5,  source: "CCQ4",       subscale: "MA", reverse: true,
    text: "I feel drowsy for a long time after awakening.",
    anchors: ["Fully disagree", "Disagree", "Neither", "Agree", "Fully agree"] },

  // Eveningness
  { id: 6,  source: "CSM13-rev",  subscale: "EV", reverse: false,
    text: "I am more an evening than a morning active person.",
    anchors: ["Fully disagree", "Disagree", "Neither", "Agree", "Fully agree"] },
  { id: 7,  source: "CCQ2-rev",   subscale: "EV", reverse: false,
    text: "I feel I can think the best in the evening.",
    anchors: ["Fully disagree", "Disagree", "Neither", "Agree", "Fully agree"] },
  { id: 8,  source: "CCQ5",       subscale: "EV", reverse: false,
    text: "If I were to study anything by myself, I would rather do it in the evening.",
    anchors: ["Fully disagree", "Disagree", "Neither", "Agree", "Fully agree"] },
  { id: 9,  source: "CCQ11-rev",  subscale: "EV", reverse: false,
    text: "I am usually in an excellent mood in the evening.",
    anchors: ["Fully disagree", "Disagree", "Neither", "Agree", "Fully agree"] },
  { id: 10, source: "CIRENS2",    subscale: "EV", reverse: false,
    text: "In general, how is your energy level in the evening?",
    anchors: ["Very low", "Low", "Moderate", "High", "Very high"] },

  // Distinctness (amplitude)
  { id: 11, source: "CCQ14",      subscale: "DI", reverse: false,
    text: "There are moments during the day where I feel unable to do anything.",
    anchors: ["Fully disagree", "Disagree", "Neither", "Agree", "Fully agree"] },
  { id: 12, source: "CCQ15",      subscale: "DI", reverse: false,
    text: "There are moments during the day when it is harder for me to think.",
    anchors: ["Fully disagree", "Disagree", "Neither", "Agree", "Fully agree"] },
  { id: 13, source: "CCQ6",       subscale: "DI", reverse: true,
    text: "My mood stays the same throughout the day.",
    anchors: ["Fully disagree", "Disagree", "Neither", "Agree", "Fully agree"] },
  { id: 14, source: "CCQ8",       subscale: "DI", reverse: true,
    text: "I can focus at any time of the day.",
    anchors: ["Fully disagree", "Disagree", "Neither", "Agree", "Fully agree"] },
  { id: 15, source: "CCQ10",      subscale: "DI", reverse: true,
    text: "At any time of the day, my motivation is the same.",
    anchors: ["Fully disagree", "Disagree", "Neither", "Agree", "Fully agree"] },
];

// ---------------------------------------------------------------------------
// 2. Scoring
// ---------------------------------------------------------------------------

// German norms from Vagos et al. 2019 (n=2096).
export const NORMS = {
  MA: { mean: 15.5, sd: 4.3 },
  EV: { mean: 15.8, sd: 4.1 },
  DI: { mean: 17.1, sd: 3.3 },
};

// `responses` is an object { 1: 1..5, 2: 1..5, ..., 15: 1..5 }.
export function scoreMESSi(responses) {
  const subs = { MA: 0, EV: 0, DI: 0 };
  for (const item of ITEMS) {
    const raw = responses[item.id];
    if (typeof raw !== "number" || raw < 1 || raw > 5) {
      throw new Error(`Item ${item.id}: response must be 1..5, got ${raw}`);
    }
    const scored = item.reverse ? 6 - raw : raw;
    subs[item.subscale] += scored;
  }
  const z = {
    MA: (subs.MA - NORMS.MA.mean) / NORMS.MA.sd,
    EV: (subs.EV - NORMS.EV.mean) / NORMS.EV.sd,
    DI: (subs.DI - NORMS.DI.mean) / NORMS.DI.sd,
  };
  return { ...subs, z, chronotype: classifyChronotype(z) };
}

// Classification by the MA-EV z-difference.
// >0.5 → morning, <-0.5 → evening, else intermediate.
export function classifyChronotype(z) {
  const diff = z.MA - z.EV;
  if (diff > 0.5) return "morning";
  if (diff < -0.5) return "evening";
  return "intermediate";
}

// ---------------------------------------------------------------------------
// 3. Alertness curve from Randler 2016 Table 10
// ---------------------------------------------------------------------------
//
// Pearson correlations between MA / EV subscale scores and self-rated alertness
// at 2-hour bins across the day. We use these as linear weights and interpolate
// linearly between bin midpoints to get a per-hour alertness function.

export const ALERTNESS_BINS = [
  { mid: 7,  bMA:  0.555, bEV: -0.259 },
  { mid: 9,  bMA:  0.565, bEV: -0.441 },
  { mid: 11, bMA:  0.457, bEV: -0.425 },
  { mid: 13, bMA:  0.195, bEV: -0.116 },
  { mid: 15, bMA:  0.005, bEV:  0.059 },
  { mid: 17, bMA: -0.104, bEV:  0.139 },
  { mid: 19, bMA: -0.104, bEV:  0.205 },
];

function interpolateBetas(hour) {
  const bins = ALERTNESS_BINS;
  if (hour <= bins[0].mid) return { bMA: bins[0].bMA, bEV: bins[0].bEV };
  if (hour >= bins[bins.length - 1].mid) {
    const last = bins[bins.length - 1];
    return { bMA: last.bMA, bEV: last.bEV };
  }
  for (let i = 0; i < bins.length - 1; i++) {
    if (hour >= bins[i].mid && hour <= bins[i + 1].mid) {
      const t = (hour - bins[i].mid) / (bins[i + 1].mid - bins[i].mid);
      return {
        bMA: bins[i].bMA * (1 - t) + bins[i + 1].bMA * t,
        bEV: bins[i].bEV * (1 - t) + bins[i + 1].bEV * t,
      };
    }
  }
  return { bMA: 0, bEV: 0 };
}

// alertness(hour, z, opts) returns an alertness score for `hour` (0..24)
// given the user's z-scored MESSi result. Higher = more alert.
// `diModulation`: if true, z_DI scales the amplitude of the curve
// (high DI → sharper peaks/troughs; low DI → flatter curve).
export function alertnessAt(hour, z, opts = {}) {
  const { diModulation = false } = opts;
  const { bMA, bEV } = interpolateBetas(hour);
  let value = bMA * z.MA + bEV * z.EV;
  if (diModulation) {
    // Bound the multiplier so a low-DI user still sees some signal.
    const mult = Math.max(0.3, Math.min(1.7, 1 + 0.3 * z.DI));
    value *= mult;
  }
  return value;
}

// Sample the alertness curve at a fixed grid for plotting / scheduling.
// Returns array of { hour, alertness }.
export function alertnessCurve(z, opts = {}) {
  const { startHour = 6, endHour = 20, stepMin = 30, diModulation = false } = opts;
  const points = [];
  const stepHours = stepMin / 60;
  for (let h = startHour; h <= endHour + 1e-9; h += stepHours) {
    points.push({ hour: h, alertness: alertnessAt(h, z, { diModulation }) });
  }
  return points;
}

// ---------------------------------------------------------------------------
// 4. The 7 pathologist tasks
// ---------------------------------------------------------------------------
//
// cogLoad in [0,1]. Higher = more sustained analytical focus required, so
// the scheduler prefers high-alertness slots for it. Lower = routine, the
// scheduler prefers low-alertness slots so peak hours are not wasted.

export const TASKS = {
  microscopy:              { label: "Microscopy work",                  cogLoad: 0.95 },
  tissue_assessment_fish:  { label: "Tissue assessment — FISH",     cogLoad: 0.85 },
  departmental_meetings:   { label: "Departmental meetings",            cogLoad: 0.50 },
  technical_validation:    { label: "Technical validation / lab support", cogLoad: 0.40 },
  emails:                  { label: "Emails",                           cogLoad: 0.10 },
};

// ---------------------------------------------------------------------------
// 5. Scheduler
// ---------------------------------------------------------------------------
//
// Cases: [{ id, taskType (key of TASKS), durationMin, urgency (0..1) }].
// Mode:
//   "chronotype"     - pure: assign by cognitive-load × alertness match.
//   "urgency"        - urgent (>=0.9) cases lock to earliest free slots first;
//                      remainder scheduled by chronotype.
//   "stability"      - chronotype-aware but DI-modulated: low-DI users get
//                      a flatter alertness curve so the order matters less.
//
// Optional workHabit (default "none") layers a soft preference on top of the
// alertness-based score with weight HABIT_WEIGHT (~10% of the alertness term).
// Alertness remains dominant; the habit only nudges placement when alertness
// scores are close. Never places tasks outside positive-alertness slots.
//
//   "none"          - no habit preference (default).
//   "finish_asap"   - prefers earlier slots so the day ends sooner.
//   "long_lunch"    - mild penalty on slots in 12:00..13:30.
//   "chill_morning" - mild penalty on slots before 10:00.
//   "focus_window"  - bonus for high-cogLoad (>=0.7) tasks at peak ±1h.
//   "crash_evening" - prefers later slots.
//
// Day window: 06:00..20:00 (default), 8h actual work, splittable.

const HABIT_WEIGHT = 0.1;

function findPeakHour(z, cfg) {
  let peakHour = cfg.dayStartHour;
  let peakAlert = -Infinity;
  for (let h = cfg.dayStartHour; h <= cfg.dayEndHour + 1e-9; h += 0.5) {
    const a = alertnessAt(h, z);
    if (a > peakAlert) { peakAlert = a; peakHour = h; }
  }
  return peakHour;
}

function habitPrefAt(slot, hour, c, ctx) {
  switch (ctx.workHabit) {
    case "finish_asap":
      return 1 - slot / Math.max(1, ctx.totalSlots - 1);
    case "crash_evening":
      return slot / Math.max(1, ctx.totalSlots - 1);
    case "long_lunch":
      return (hour >= 12 && hour < 13.5) ? -1 : 0;
    case "chill_morning":
      return hour < 10 ? -1 : 0;
    case "focus_window":
      return (c.cogLoad >= 0.7 && Math.abs(hour - ctx.peakHour) <= 1) ? 1 : 0;
    default:
      return 0;
  }
}

export const DEFAULTS = {
  dayStartHour: 6,
  dayEndHour: 20,
  workMinutes: 8 * 60,
  slotMin: 30,
};

function hourToLabel(hour) {
  const h = Math.floor(hour);
  const m = Math.round((hour - h) * 60);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

export function schedule(cases, z, opts = {}) {
  const cfg = { ...DEFAULTS, ...opts };
  const mode = opts.mode ?? "chronotype";
  const workHabit = opts.workHabit ?? "none";
  const totalSlots = ((cfg.dayEndHour - cfg.dayStartHour) * 60) / cfg.slotMin;
  const targetWorkSlots = cfg.workMinutes / cfg.slotMin;
  const peakHour = workHabit === "focus_window" ? findPeakHour(z, cfg) : 0;

  // Per-slot alertness (sampled at slot midpoint).
  const alertness = [];
  for (let s = 0; s < totalSlots; s++) {
    const hour = cfg.dayStartHour + (s * cfg.slotMin + cfg.slotMin / 2) / 60;
    alertness.push(alertnessAt(hour, z, { diModulation: mode === "stability" }));
  }

  // Cases in priority order.
  let queue = cases.map((c) => ({
    ...c,
    cogLoad: TASKS[c.taskType]?.cogLoad ?? 0.5,
    needSlots: Math.max(1, Math.ceil(c.durationMin / cfg.slotMin)),
  }));

  if (mode === "urgency") {
    // STAT first (earliest slot), then by cog load DESC.
    queue.sort((a, b) => {
      const aStat = a.urgency >= 0.9 ? 1 : 0;
      const bStat = b.urgency >= 0.9 ? 1 : 0;
      if (aStat !== bStat) return bStat - aStat;
      return b.cogLoad - a.cogLoad;
    });
  } else {
    queue.sort((a, b) => b.cogLoad - a.cogLoad);
  }

  const occupied = new Array(totalSlots).fill(null);
  const scheduled = [];
  let workSlotsUsed = 0;

  for (const c of queue) {
    if (workSlotsUsed + c.needSlots > targetWorkSlots) continue;

    const isStat = mode === "urgency" && c.urgency >= 0.9;
    let bestStart = -1;
    let bestScore = -Infinity;

    for (let s = 0; s + c.needSlots <= totalSlots; s++) {
      let free = true;
      for (let k = 0; k < c.needSlots; k++) {
        if (occupied[s + k] !== null) { free = false; break; }
      }
      if (!free) continue;

      let mean = 0;
      for (let k = 0; k < c.needSlots; k++) mean += alertness[s + k];
      mean /= c.needSlots;

      let habitMean = 0;
      if (workHabit !== "none") {
        const habitCtx = { workHabit, totalSlots, peakHour };
        for (let k = 0; k < c.needSlots; k++) {
          const slotIdx = s + k;
          const slotHour =
            cfg.dayStartHour + (slotIdx * cfg.slotMin + cfg.slotMin / 2) / 60;
          habitMean += habitPrefAt(slotIdx, slotHour, c, habitCtx);
        }
        habitMean /= c.needSlots;
      }

      let score;
      if (isStat) {
        // earliest free slot wins; tiebreak by alertness + habit match
        score = -s * 1000 + mean * (2 * c.cogLoad - 1) + HABIT_WEIGHT * habitMean;
      } else {
        // (2*cogLoad - 1) inverts preference for low-load tasks: high-cog tasks
        // want positive alertness slots, low-cog tasks prefer trough slots.
        // habitMean is a soft nudge with HABIT_WEIGHT << 1.
        score = mean * (2 * c.cogLoad - 1) + HABIT_WEIGHT * habitMean;
      }

      if (score > bestScore) {
        bestScore = score;
        bestStart = s;
      }
    }

    if (bestStart < 0) continue;

    for (let k = 0; k < c.needSlots; k++) occupied[bestStart + k] = c.id;
    workSlotsUsed += c.needSlots;

    let mean = 0;
    for (let k = 0; k < c.needSlots; k++) mean += alertness[bestStart + k];
    mean /= c.needSlots;

    const startHour =
      cfg.dayStartHour + (bestStart * cfg.slotMin) / 60;
    const endHour =
      cfg.dayStartHour + ((bestStart + c.needSlots) * cfg.slotMin) / 60;

    scheduled.push({
      id: c.id,
      taskType: c.taskType,
      label: TASKS[c.taskType]?.label ?? c.taskType,
      cogLoad: c.cogLoad,
      urgency: c.urgency,
      durationMin: c.durationMin,
      startSlot: bestStart,
      endSlot: bestStart + c.needSlots,
      startHour,
      endHour,
      startLabel: hourToLabel(startHour),
      endLabel: hourToLabel(endHour),
      meanAlertness: mean,
    });
  }

  scheduled.sort((a, b) => a.startSlot - b.startSlot);
  const skipped = queue.filter((c) => !scheduled.some((s) => s.id === c.id));

  return {
    mode,
    workHabit,
    z,
    config: cfg,
    alertness: alertness.map((a, i) => ({
      slot: i,
      hour: cfg.dayStartHour + (i * cfg.slotMin + cfg.slotMin / 2) / 60,
      alertness: a,
    })),
    scheduled,
    skipped: skipped.map((c) => ({ id: c.id, taskType: c.taskType, reason: "no_capacity" })),
    workMinutesUsed: workSlotsUsed * cfg.slotMin,
  };
}

export const WORK_HABITS = [
  { id: "none",          label: "None",          description: "No habit preference (default). Pure alertness-driven." },
  { id: "finish_asap",   label: "Finish ASAP",   description: "Soft preference for earlier slots. Free evening." },
  { id: "long_lunch",    label: "Long lunch",    description: "Soft penalty for slots in 12:00–13:30 so a midday gap appears." },
  { id: "chill_morning", label: "Chill morning", description: "Soft penalty for slots before 10:00 so the day starts later." },
  { id: "focus_window",  label: "Focus window",  description: "Bonus for high-cogLoad tasks at your peak ±1h." },
  { id: "crash_evening", label: "Crash evening", description: "Soft preference for later slots." },
];
