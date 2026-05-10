#!/usr/bin/env bash
# One-shot setup for the SOPHiA DDM AI Triage + Chatbot backend.
#
# Creates .venv, installs Python deps, downloads Playwright's Chromium
# (needed for the headless Gen2 login). Idempotent — safe to re-run.

set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "error: $PYTHON not found. Install Python 3.10+ or set PYTHON=/path/to/python3." >&2
  exit 1
fi

if [ ! -d .venv ]; then
  echo ">>> creating venv at .venv (using $PYTHON)"
  "$PYTHON" -m venv .venv
fi

# shellcheck source=/dev/null
source .venv/bin/activate

echo ">>> upgrading pip"
pip install --quiet --upgrade pip

echo ">>> installing Python deps from requirements.txt"
pip install --quiet -r requirements.txt

echo ">>> installing Playwright Chromium (used by auth.py for Gen2 login)"
python -m playwright install chromium

cat <<'EOF'

Setup complete.

Next:
  1.  cp .env.example .env && $EDITOR .env       # paste your API key(s)
  2.  source .venv/bin/activate
  3.  set -a; source .env; set +a
  4.  python -m src.llm_report.api               # serves on http://127.0.0.1:8000

Then load the extension/ folder in chrome://extensions/ (Developer Mode → Load unpacked).
EOF
