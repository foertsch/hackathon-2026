# hackathon-2026

Team repository for **The Future of Health Hackathon** (ETH Zürich, May 8–10, 2026).
Genomics track.

## Team
- Jędrzej Kubica
- Herman Galioulline
- Evangelia N.
- Nat Graff
- Arion Förtsch

## Status
Pre-event setup. Tooling: Python · R · Claude · Lovable · Hugging Face.

## Challenge
Sponsor: **Sophia Genetics**. Goal: build a tool on top of **Sophia DDM** that makes the genomic pathologist faster without compromising correctness.
Briefing summary → [`challenge_transcript.md`](challenge_transcript.md). Raw transcript → [`transcripts/`](transcripts/).

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

## Repo layout
- `challenge_transcript.md` — structured briefing summary (LLM-friendly).
- `transcripts/` — raw transcription (txt/srt/vtt) of the Sat morning briefing.
- `docs/` — Sophia VQS API reference + screenshots + sample response.
- `scripts/vqs_query.py` — minimal VQS client (stdlib only, no deps).
- `decisions.md`, `mentors.md` — team working docs.

### Projects
- [`ai-triage-extension/`](ai-triage-extension/): Chrome MV3 extension that injects an AI case summary card into the Gen2 sample side panel, paired with a FastAPI backend that builds the bundle from VQS and drafts the summary with Gemini 2.5 Flash. Priority is computed deterministically from typed ACMG / ClinVar / ABCD fields; bullet text passes through a token-level verifier against the source bundle. See [`ai-triage-extension/extension/README.md`](ai-triage-extension/extension/README.md) for setup.
