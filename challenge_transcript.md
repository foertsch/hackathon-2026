# Sophia Genetics Challenge — Briefing Summary

> Structured, LLM-ready summary of the live challenge briefing delivered by the Sophia Genetics team (Abhi, Shubham, Antonio, Jesus) at The Future of Health Hackathon, ETH Zürich, 2026-05-09.
>
> Source recording: `transcripts/20260509_100559.{txt,srt,vtt}` (29:12, English, transcribed with faster-whisper `medium` model). Quote and timestamp references use the `.srt` file.

---

## TL;DR

Build something on top of **Sophia DDM** (the Sophia Genetics genomic-analysis platform) that **shortens the time a genomic pathologist spends per case** without sacrificing correctness. The ultimate clinical output is a signed PDF report (or JSON for EHR integration). Useful API access will be provided. The judging mantra: *less time in the software = better, but only if the result stays correct.*

---

## 1. Who is Sophia Genetics?

- Swiss company, ~15 years old, spun out of EPFL by a former wet-lab biologist.
- IPO'd in 2021. ~430 employees today.
- Serves **800+ institutions** worldwide; has run **2.5M+ genomic profiles**.
- Mission: *"democratize data-driven medicine"* — connect multi-modal patient data (genomics, radiomics, clinical) across geographies so insights from one patient help similar patients elsewhere.

## 2. The Platform — Sophia DDM

- Cloud-based, decentralized analytics platform.
- Hundreds of products; each product is essentially a **gene panel** targeted at a specific disease class.
- Two distinct user groups:
  1. **Lab professionals** — geneticists, bioinformaticians, pathologists. They process raw genomic data and produce a **genomic report**. ← *This challenge focuses here.*
  2. **Oncologists / clinicians** — consume the report to choose a treatment plan.
- The challenge will work specifically with the **genomics module**.

## 3. Genomics Primer (so an LLM can reason about the domain)

### 3.1 Variants
A **variant** = a deviation in a patient's DNA relative to a reference genome.

| Class | Origin | Example use case |
|---|---|---|
| **Germline** | Inherited or *de novo* at conception. Detected from blood. | Hereditary cancer screening |
| **Somatic** | Acquired over the patient's lifetime. Detected from tumor tissue. | Tumor profiling (e.g., MSK-ACCESS) |

Variants are also classified by clinical impact:

| Bucket | Meaning | UI color (Sophia DDM variant table) |
|---|---|---|
| **Benign** | Difference vs. reference, but harmless. | Green |
| **VUS** (Variant of Unknown Significance) | Insufficient evidence. | Blue |
| **Pathogenic** | Causes / contributes to disease. | Red (in "interpretation" column) |

### 3.2 Cancer Progression (one-line model)
> DNA damage → mutation → unregulated proliferation (tumor suppressor fails) → tumor reaches critical mass → cancer → metastasis (if untreated).

Cancer is **a process over years/decades**, not a single event.

### 3.3 Patient Journey
1. Symptoms appear, persist.
2. Patient sees GP → observation period.
3. Referral to scan / imaging.
4. If abnormal → oncologist.
5. Oncologist orders **biopsy** → H&E staining and/or **genomic testing**.
6. Genomic results determine: tumor type, aggressiveness, treatment plan.
7. Treatment + recurring monitoring loop.

> **Key insight**: genomic testing is the gating step where treatment actually begins. Time spent waiting on the pathologist's interpretation = time the patient is untreated.

## 4. A Day in the Life of a Genomic Pathologist

Genomic interpretation is *one* responsibility among many:

- Administrative work
- Lab director duties
- Wet-lab oversight
- Departmental reviews
- Hematopathology
- Molecular surveys
- **Interpreting genomic analyses** ← the part this challenge can speed up

### Compounding pressures
- **35% of FDA-approved treatments today require genomic analysis** (and rising).
- Medical knowledge doubling time has collapsed from ~50 years to ~1 year — a pathologist's knowledge becomes "half-relevant" within a year.
- ~7.5 exabytes/year of genomic data globally; **~100 GB per single analysis**.
- Pressure to increase throughput while keeping accuracy.

### A typical Monday
Pathologist arrives → analyses queued from weekend runs → must triage, interpret, write report for each → patient blocked on this step.

## 5. Sophia DDM — Walkthrough of the UI (from Antonio's demo)

### 5.1 Hierarchy
```
Application (gene panel, e.g. "Hereditary Cancer Solution")
└── Run         ← a batch of analyses processed together
    └── Sample  ← one sample = one patient (typically)
        └── Interpretation  ← one pathologist's assessment of the sample
                            (multiple interpretations per sample possible)
```

### 5.2 Interpretation View — Five tabs

1. **Overview** — summary; entry point linking to the detail tabs.
2. **Quality** — QC metrics (catches lab-prep biases, sample integrity issues).
3. **Genes** — gene-level info from the panel.
4. **Variants** — *the heart of the work.* List of all detected variants with rich annotation columns (type, frequency, predicted effect, classification, etc.). Heavy filter system available.
5. **Report** — variants flagged for inclusion get pushed here; final output.

### 5.3 Variant table — what pathologists actually do
- Sort / filter the variant list (column-based filters: equality, ranges, categories).
- Investigate borderline calls in depth (each variant has many drill-down details).
- **Flag** a variant with their assessment ("I believe this is pathogenic"). Flags propagate across Sophia's network — other clients globally see the community signal.
- Add finalized variants to the report.

### 5.4 The output
- A **signed PDF** (still the dominant deliverable in clinical practice).
- For integrated customers: **JSON** ingested by an EHR system.

## 6. The Challenge

### 6.1 Goal
> *"Build something on top of the platform that improves the day of a genomic pathologist."*

The single north-star metric: **get the right information to patients faster.**

### 6.2 Scope rules
- Use the Sophia DDM **APIs and test account** provided (credentials shared separately).
- Build *on top of* the platform (no need to fork or reimplement it).
- Ideas you can only ship "next Monday" are out — must be demoable today.

### 6.3 Suggested directions (non-exhaustive)
| Idea | What it would do |
|---|---|
| **Auto-report generation** | Pull data from the interpretation view, generate a draft report via LLM. *Critical: no hallucinations* — must be precise; misdiagnosis risk is the dominant constraint. |
| **Smart variant pre-flagging** | Use the variant API to suggest which variants deserve pathologist attention first — beat the platform's existing flagging. |
| **Natural-language filter editor** | User types a sentence; system translates to the structured variant-table filter. |
| **Caseload optimization** | Help the pathologist triage / sequence their backlog of cases more efficiently. |
| **Anything else creative** | Open-ended — surprise them. |

### 6.4 Required skill mix (per Abhi)
- Genomics literacy (variants, VUS, classification, somatic vs. germline).
- Process / workflow thinking (lab with 120 staff, 200 reports/day — how does it scale?).
- Engineering (APIs, tooling).
- Data science / AI (where it adds value safely).

## 7. Evaluation Criteria

The team explicitly named three axes:

1. **User-experience improvement** — measured *inversely* to time the user spends in the tool. Less click-time per correct report = better.
2. **Technical execution** — working demo preferred, but if you don't finish, *clearly explain what you would have built*. Partial credit available.
3. **Innovation** — novelty matters; impress them.

## 8. Hard Constraints

- **Correctness > everything.** A hallucinated variant call or misclassification can misdiagnose a patient. Don't ship LLM output that hasn't been grounded in the actual platform data.
- The test instance is shared with other teams — be reasonable with API load.

## 9. Mentors / Contacts (named in the briefing)

- **Abhi** — product / business framing.
- **Shubham** — genomics primer (recently moved into healthtech from travel/hospitality).
- **Antonio** — Sophia DDM demo.
- **Jesus** — challenge framing & evaluation.

All four are available on-site for questions throughout the hackathon.

## 10. Glossary (for downstream LLM context)

- **Sophia DDM** — Sophia's "Democratizing Data-driven Medicine" analytics platform.
- **Gene panel** — a curated set of genes targeted by a specific assay.
- **Run** — a batch of lab analyses processed together.
- **Sample** — typically one patient's data within a run.
- **Interpretation** — a pathologist's assessment of a sample (several possible per sample).
- **Variant** — DNA difference vs. the reference genome.
- **Germline / Somatic** — inherited vs. acquired variant.
- **VUS** — Variant of Unknown Significance.
- **H&E** — Hematoxylin and Eosin staining (histology).
- **EHR** — Electronic Health Record.

---

## Appendix A — Source files

- Full plain-text transcript: [`transcripts/20260509_100559.txt`](transcripts/20260509_100559.txt)
- Subtitles (timed): [`transcripts/20260509_100559.srt`](transcripts/20260509_100559.srt), [`transcripts/20260509_100559.vtt`](transcripts/20260509_100559.vtt)
- Original video: `~/Downloads/20260509_100559.mp4` (2.5 GB, not committed).
- Transcription: [`faster-whisper`](https://github.com/SYSTRAN/faster-whisper) v1.2.1, model `medium`, language auto-detected English (98% confidence), CPU `int8` quantization on Apple Silicon.
