# SOPHiA DDM AI Triage + Chatbot

A Chrome extension that adds two glanceable AI affordances to the SOPHiA DDM
Gen2 worklist, backed by a small FastAPI service:

- **Triage card** — a priority badge, one-line headline, and 4–5 verified
  bullets injected next to each case in the side panel. Priority is computed
  *deterministically* from typed ACMG / ClinVar / ABCD fields; only short
  prose pieces (headline, volume note, discrepancy note) come from an LLM,
  and every value-bearing token is checked against the source bundle.
- **Case chatbot** — single-case Q&A scoped to the open sample. The
  pathologist asks questions ("what's the highest-priority variant?", "any
  ACMG/ClinVar disagreements?", "show me low-VAF calls"); the assistant
  answers using only the cached case bundle and is instructed to refuse on
  data outside it.

> _Screenshot placeholder — add `docs/triage-card-and-chat.png` and reference
> it here once captured._

## Why this design

Two competing claims dominate the AI-for-pathology space: that LLMs can
shorten review time, and that they hallucinate enough to be unsafe. We
split the difference *structurally*. The LLM only writes prose, never
decides priority or selects which variant a bullet talks about, and a
token-level verifier surfaces a ✓ / ! / T chip on every bullet (✓ verified,
! at least one token missing from cited evidence, T templated — no LLM in
the loop). The chatbot inherits the same contract: the model sees a typed
[`CaseBundle`](src/llm_report/case_bundle.py) (sample header, QC indicators,
every variant with provenance), is told to cite `sg_id` for variant-specific
claims, and the UI labels the panel _"single-case scope · verify clinical
claims"_ so the trust boundary is explicit.

## Quick start (~5 minutes)

You need:
- Python 3.10+ and Chrome
- Hackathon Gen2 credentials (the test platform isn't open to the public)
- One of: `GEMINI_API_KEY` (free tier works for a handful of cases) or
  `ANTHROPIC_API_KEY` (paid; more reliable under load)

```bash
cd ai-triage-extension
./setup.sh                            # creates .venv, installs deps + Playwright Chromium
cp .env.example .env && $EDITOR .env  # paste your API key(s) and pick a model
source .venv/bin/activate
set -a; source .env; set +a
python -m src.llm_report.api          # backend listens on http://127.0.0.1:8000
```

In Chrome:

1. Open `chrome://extensions/`, enable Developer Mode, click **Load
   unpacked**, and select the `ai-triage-extension/extension/` folder.
2. Visit <https://platform-vandv1.sophiagenetics.com/web/genomics> and log
   in with the hackathon credentials. The backend caches the session, so
   re-login isn't required after the first run.
3. Click into a sample. The triage card appears in ~5–8 s on first run
   (LLM call + VQS pull) and instantly thereafter. The chat input enables
   once the triage card has rendered.

## What to look for

The Hereditary Cancer run has two pre-loaded samples — start with
**`SG063-LPA`**, which has the richest evidence (multiple ACMG-classified
variants, ClinVar overlap).

On the **triage card:**

- Hover the chip on each bullet:
  - **✓** — LLM-written prose; every value-bearing token verified against cited evidence.
  - **T** — templated bullet; assembled deterministically from typed fields, no LLM.
  - **!** — at least one token didn't appear in cited evidence (rare; click for the offending tokens).
- ACMG / ClinVar phrases like _Conflicting classifications of pathogenicity_ render in italic spaces, not raw underscores.

On the **chat panel** (below the card):

- The eyebrow shows _"SOPHiA AI · Case Chat · [sample userRef]"_ — the chip is the scope-of-conversation cue.
- Try:
  - "What's the highest-priority variant and why?"
  - "Any disagreements between ACMG and ClinVar in this case?"
  - "Show me variants with VAF below 10 percent."
  - "Anything in BRCA2 in other samples?" — should decline (out-of-scope).

## Configuration

Set in `.env` (see `.env.example`):

| Env var | Default | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | _none_ | Used when `LLM_MODEL` / `CHAT_MODEL` start with `gemini`. |
| `ANTHROPIC_API_KEY` | _none_ | Used when models do **not** start with `gemini` (Claude path). |
| `LLM_MODEL` | `gemini-2.5-flash` | Triage card model. Set to e.g. `claude-sonnet-4-6` to use Claude. |
| `CHAT_MODEL` | `gemini-2.5-flash` | Chatbot model. Independent of triage. |
| `PORT` | `8000` | Backend port. The extension hardcodes `127.0.0.1:8000`; if you change this, also update `BACKEND` in `extension/content.js` and the manifest's `host_permissions`. |

## Architecture

Backend ([`src/llm_report/`](src/llm_report/)):

- `auth.py` — runs an Azure B2C login via headless Playwright once and caches cookies.
- `vqs_client.py` — wraps Gen2's GraphQL + Variant Query Service.
- `bundle_builder.py` — assembles a typed [`CaseBundle`](src/llm_report/case_bundle.py) per sample.
- `ranker.py` — derives priority + actionable variants from typed evidence (no LLM).
- `bullet_templates.py` — composes templated finding bullets without an LLM.
- `summary_drafter.py` — calls Gemini/Claude for the short prose pieces only.
- `verifier.py` — token-level check of LLM prose against cited evidence.
- `chat.py` — per-case Q&A endpoint over the same `CaseBundle`.
- `api.py` — FastAPI router; caches everything to `build/` keyed by sample / interpretation id.

Extension ([`extension/`](extension/), Chrome MV3):

- `content.js` — observes the Gen2 SPA via `MutationObserver`, finds the side panel, injects the card + chat.
- `background.js` — service-worker fetch proxy. Loopback fetches from the page origin are blocked by Chrome's Private Network Access policy; the SW does them with extension-origin privileges.
- `content.css` — styling for the injected DOM.

## Layout

```
ai-triage-extension/
├── README.md                 ← you are here
├── setup.sh                  ← venv + deps installer
├── .env.example              ← API key template
├── requirements.txt
├── src/llm_report/           ← FastAPI backend (Python)
├── extension/                ← Chrome MV3 extension (HTML/CSS/JS)
└── inventory/                ← Gen2 API reverse-engineering notes
```

## Honest constraints

- **Requires SOPHiA Gen2 credentials.** No public dataset; you need the hackathon login.
- **Requires an LLM API key with budget.** ~$0.01–0.03 per chat turn or per fresh triage card with Sonnet 4.6. Gemini 2.5 Flash free tier works for a handful of cases before quota resets.
- **First-time per sample is slow** (~5–8 s) — the bundle has to be pulled and the summary generated. Subsequent loads + chat turns are instant aside from the LLM round-trip.
- **No streaming on chat.** Replies arrive after a single round-trip.
- **No persistence on chat history.** In-memory per sample; reloading Gen2 wipes it. Triage summaries persist on disk in `build/`.
