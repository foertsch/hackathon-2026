# SOPHiA DDM AI Triage — Chrome extension

Adds an AI-generated triage panel next to each interpretation in Gen2's
"My work" view. Talks to a local FastAPI backend at `http://127.0.0.1:8000`.

## Setup

1. Start the backend (in another terminal):
   ```
   export GEMINI_API_KEY=...
   python3 -m src.llm_report.api
   ```
   The server listens on `http://127.0.0.1:8000`. Visit
   `http://127.0.0.1:8000/` to see the standalone triage view.

2. Load the extension in Chrome:
   - Open `chrome://extensions/`
   - Enable Developer mode (top right)
   - Click "Load unpacked"
   - Select the `extension/` directory

3. Visit
   `https://platform-vandv1.sophiagenetics.com/web/genomics`
   and log in with the hackathon credentials.

   Each card in "My work" should sprout an "AI Triage" panel within ~2-3
   seconds (cached cases) or ~5-8 seconds (fresh summarisation).

## Architecture

- `manifest.json` — MV3 manifest, declares the content script.
- `content.js` — runs on every Gen2 page; finds card titles whose text
  matches an interpretation name from the backend, then injects a panel.
- `content.css` — styling for the injected panel.

The backend is the brains: it owns the Gen2 session, builds bundles via VQS,
calls Gemini, validates, and caches summaries to disk under `build/`.

## Case chat

Below the triage card, the side panel includes a chat box scoped to the
currently open sample. The backend endpoint is
`POST /api/sample-chat/{sample_id}`, body `{messages: [{role, content}]}`,
returning `{reply}`. It loads the cached bundle + summary + context for the
sample and runs them through `chat.py` (Gemini by default,
`CHAT_MODEL=claude-sonnet-4-6` to switch).

History is held in memory per sample for the lifetime of the page; closing
or reloading Gen2 wipes it. The chat won't activate until the triage
summary has finished generating for the sample, since both the bundle and
summary need to be on disk first.

Chat replies are NOT verified by the token-level verifier the triage card
uses — they're labelled "verify clinical claims independently" in the UI.
