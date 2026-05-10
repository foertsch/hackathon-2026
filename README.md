> **The Future of Health Hackathon** (ETH Zürich, May 8–10, 2026)

# Alleles in Wonderland

## Challenge 

Hackathon weekend. Genomics track. Aim: build a tool on top of **Sophia Genetics Platform** that facilitates the genomic pathologist's work.

Two products live in this repo, both wired into the Sophia Genetics Platform via Chrome extensions.

Briefing summary → [`challenge_transcript.md`](challenge_transcript.md).

Raw transcript → [`transcripts/`](transcripts/).

Tooling: Python · R · Claude · Lovable · Hugging Face.


## Contributors
- Jędrzej Kubica
- Herman Galioulline
- Evangelia N.
- Nat Graff
- Arion Förtsch


## Repo layout
- `challenge_transcript.md` — structured briefing summary
- `transcripts/` — raw transcription of the challenge briefing on the first day of the hackathon
- `docs/` — Sophia VQS API reference + screenshots + sample response
- `scripts/vqs_query.py` — minimal VQS client.
- `decisions.md`, `mentors.md` — team working docs

### Products

Two complementary products, both reachable from the pathologist's existing Sophia Platform:

- [`ai-triage-extension/`](ai-triage-extension/): Chrome extension that injects a case-specific bullet point summary the sample side panel, paired with a backend that drafts the summary with Gemini 2.5 Flash. The priority of information in the summary is computed based on genomic variant classifications (ACMG / ClinVar / Sophia ABCD). See [`ai-triage-extension/extension/README.md`](ai-triage-extension/extension/README.md) for setup.

- **PathoChrono** — chronotype-based planner that orders the pathologist's day-to-day tasks (e.g. microscopy, FISH) according to with their personal alertness peak. During the hackathon it is available at <https://patho-chrono-flow.lovable.app/>. Pathologist answers a short 3-minute questionnaire (MESSi, Randler 2016) at the account set-up, then scheduler matches their alertness across Monday–Friday work time. This product has three parts:
  - [`messi/`](messi/) — node ESM scoring + scheduler core (`messi.mjs`, tests in `messi.test.mjs`), synthetic caseloads, and a PDF report generator.
  - [`patho-chrono-companion/`](patho-chrono-companion/) — submodule pointing at the webapp (Lovable React).
  - [`pathochrono-launcher/`](pathochrono-launcher/) — tiny Chrome MV3 extension that adds a **Scheduler** button next to the "Welcome" greeting on the Gen2 landing page; click it, the live PathoChrono app opens in a new tab. No backend.

The two extensions coexist within the Chrome browser, so a pathologist running both sees: a Scheduler button on the landing page and a case summary in the side panel.


## Demo

TODO screenshots


## API access (Variant Query Service)

Reference docs from Sophia → [`docs/VQS-API.md`](docs/VQS-API.md). Sample response → [`docs/sample_response.json`](docs/sample_response.json).

**Get a token (1h TTL).** Log into the platform with the team account, then visit
<https://iam-vandv.sophiagenetics.com/account/token> and copy the `access_token` field.

```bash
export IAM_TOKEN="paste-here"
```

**Smoke-test against the demo interpretation:**
```bash
./scripts/vqs_query.py query \
  --key "eyJmaWNJZCI6MjA2NTA3NTM4LCJrbm93bkZpbGUiOiJMQVlFUjJfU0hPUlRfU1VCU0VUX0RBVEFTRVRfUExVU19HRU5FX0FOTk9UQVRJT05TIiwiYW5hbHlzaXNJZCI6MjAwMDQyMzYwLCJpbnRlcnByZXRhdGlvbiI6ImludGVycHJldGF0aW9uLTEwNDIiLCJ0cmFuc2NyaXB0U3RyYXRlZ3lWZXJzaW9uIjoiMTc3ODA2OTAyNjAwMCJ9" \
  --analysis-id 200042360 \
  --interpretation-id interpretation-1042 \
  --experiment-type-id 126000 \
  --transformers FLATTEN,SHORT_SUBSET \
  --body scripts/example_query.json
```
Should return JSON with 524 columns × 10 rows. To grab `key`/`analysisId`/`interpretationId` for a different sample, open the platform → Variants view → DevTools Network tab → "Copy as cURL" on a query → extract the params.

**Decode a key:** `./scripts/vqs_query.py decode-key "<base64>"` → prints the JSON inside.

> Note on doc inconsistency: the live API expects bare query params (`key=`, `plan.parameters.X=`, `plan.transformers=`), not the `parameters.`-prefixed form shown in some snippets of `VQS-API.md`. The wrapper handles this.
