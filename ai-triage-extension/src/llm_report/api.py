"""
FastAPI backend for the Smart Case Summary product.

Endpoints:
  GET  /api/interpretations         — list pending interpretations (from VQS search)
  GET  /api/summary/{id}            — get one summary (builds + caches if missing)
  POST /api/summary/{id}/refresh    — force re-summarize
  GET  /api/summaries               — all summaries that exist on disk
  GET  /                            — standalone triage HTML (fallback view)

CORS is open so the Chrome extension running on the Gen2 origin can call us.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from .auth import get_session
from .bundle_builder import build_case_bundle
from .case_bundle import CaseBundle
from .case_summary import CaseSummary
from .chat import DEFAULT_MODEL as CHAT_DEFAULT_MODEL, chat_about_sample
from .sanitizer import clean_summary
from .summary_drafter import summarize_case
from .verifier import verify_summary
from .vqs_client import VQSClient

REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD_DIR = REPO_ROOT / "build"
TEMPLATES_DIR = REPO_ROOT / "src" / "llm_report" / "templates"

DEFAULT_MODEL = os.environ.get("LLM_MODEL", "gemini-2.5-flash")

app = FastAPI(title="Smart Case Summary")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _allow_private_network(request, call_next):
    """Chrome blocks HTTPS pages fetching HTTP localhost unless the response
    carries this header (Private Network Access policy)."""
    response = await call_next(request)
    response.headers["Access-Control-Allow-Private-Network"] = "true"
    return response


# ---- shared state (cheap singleton; rebuilt on first request) ----

_session_holder: dict = {}


def _get_client() -> VQSClient:
    if "client" not in _session_holder:
        _session_holder["client"] = VQSClient(get_session())
    return _session_holder["client"]


def _refresh_client() -> VQSClient:
    """Force a fresh login + bearer; replace the cached client."""
    _session_holder["client"] = VQSClient(get_session(force_refresh=True))
    return _session_holder["client"]


def _summary_path(interpretation_id: str) -> Path:
    return BUILD_DIR / f"{interpretation_id}.summary.json"


def _bundle_path(interpretation_id: str) -> Path:
    return BUILD_DIR / f"{interpretation_id}.bundle.json"


def _read_summary(interpretation_id: str) -> Optional[CaseSummary]:
    p = _summary_path(interpretation_id)
    if not p.exists():
        return None
    try:
        return CaseSummary.model_validate_json(p.read_text())
    except Exception:
        return None


def _ensure_summary(interpretation_id: str, *, model: str, refresh: bool = False) -> CaseSummary:
    if not refresh:
        s = _read_summary(interpretation_id)
        if s is not None:
            return s

    client = _get_client()

    # Build or load bundle.
    bp = _bundle_path(interpretation_id)
    if bp.exists() and not refresh:
        bundle = CaseBundle.model_validate_json(bp.read_text())
    else:
        bundle = build_case_bundle(client, interpretation_id)
        BUILD_DIR.mkdir(parents=True, exist_ok=True)
        bp.write_text(bundle.model_dump_json(indent=2))

    summary, _usage = summarize_case(bundle, model=model)
    _summary_path(interpretation_id).write_text(summary.model_dump_json(indent=2))
    return summary


# ---- API routes ----


@app.get("/api/runs")
def list_runs() -> dict:
    client = _get_client()
    q = """
    query findNGSRuns($page: NGSRunPaginated!) {
      findNGSRuns(page: $page) {
        id userRef status insertDate
        samples { id sgaPipId }
      }
    }
    """
    data = client.graphql(q, {"page": {"limit": 100, "where": {"pipIds": []}}})
    runs = data.get("findNGSRuns", []) or []
    return {"runs": [
        {
            "id": r["id"],
            "user_ref": r.get("userRef"),
            "status": r.get("status"),
            "sample_count": len(r.get("samples", []) or []),
        } for r in runs
    ]}


@app.get("/api/run/{run_id}/samples")
def list_run_samples(run_id: int) -> dict:
    client = _get_client()
    q = """
    query findNGSRuns($page: NGSRunPaginated!) {
      findNGSRuns(page: $page) {
        id userRef
        samples { id sgaPipId }
      }
    }
    """
    data = client.graphql(q, {"page": {"limit": 100, "where": {"pipIds": []}}})
    runs = data.get("findNGSRuns", []) or []
    run = next((r for r in runs if int(r["id"]) == int(run_id)), None)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run {run_id} not found")
    sample_ids = [s["id"] for s in (run.get("samples") or [])]
    if not sample_ids:
        return {"run_id": run_id, "samples": []}
    sample_records = client.find_samples_by_ids(sample_ids)
    return {
        "run_id": run_id,
        "run_user_ref": run.get("userRef"),
        "samples": [
            {
                "id": s["id"],
                "user_ref": s.get("userRef"),
                "ngs_run_id": s.get("ngsRunId"),
                "experiment_type_id": s.get("experimentTypeId"),
                "sga_pip_id": s.get("sgaPipId"),
                "has_summary": (BUILD_DIR / f"sample-{s['id']}.summary.json").exists(),
            }
            for s in sample_records
        ],
    }


def _sample_summary_path(sample_id: int) -> Path:
    return BUILD_DIR / f"sample-{sample_id}.summary.json"


def _sample_context_path(sample_id: int) -> Path:
    return BUILD_DIR / f"sample-{sample_id}.context.json"


def _sample_bundle_path(sample_id: int) -> Path:
    return BUILD_DIR / f"sample-{sample_id}.bundle.json"


def _ensure_sample_summary(
    sample_id: int, *, model: str, refresh: bool = False
) -> tuple[CaseSummary, dict]:
    """Return (summary, context). The context is a small dict carrying the
    structured QC indicators + sample metadata that the extension renders
    directly (so QC-fail signals don't depend on LLM phrasing)."""
    sp = _sample_summary_path(sample_id)
    cp = _sample_context_path(sample_id)
    bp = _sample_bundle_path(sample_id)
    # Bundle is required for the chat endpoint, so a cache miss on it forces
    # full regeneration even when summary + context are present.
    if not refresh and sp.exists() and cp.exists() and bp.exists():
        try:
            return (
                CaseSummary.model_validate_json(sp.read_text()),
                json.loads(cp.read_text()),
            )
        except Exception:
            pass
    client = _get_client()
    from .bundle_builder import build_sample_bundle
    bundle = build_sample_bundle(client, sample_id)
    summary, _usage = summarize_case(bundle, model=model)
    summary = clean_summary(summary)
    verifications = verify_summary(summary, bundle)
    context = {
        "sample_user_ref": bundle.sample.sample_user_ref,
        "panel_label": bundle.sample.panel_label,
        "experiment_type": bundle.sample.experiment_type,
        "reference_genome": bundle.sample.reference_genome,
        "qc_indicators": [
            {
                "name": q.name,
                "description": q.description,
                "status": q.status,
                "value": q.value,
                "range_lower": q.range_lower,
                "range_upper": q.range_upper,
            }
            for q in bundle.qc_indicators
        ],
        "variants_total": bundle.variant_count,
        "verification": [
            {
                "slot": v.slot,
                "verified": v.verified,
                "total_tokens": v.total_tokens,
                "unverified_tokens": v.unverified_tokens,
            }
            for v in verifications
        ],
    }
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    sp.write_text(summary.model_dump_json(indent=2))
    cp.write_text(json.dumps(context, indent=2))
    # Bundle persisted alongside so /api/sample-chat can answer questions
    # without re-pulling from VQS on every turn.
    _sample_bundle_path(sample_id).write_text(bundle.model_dump_json(indent=2))
    return summary, context


@app.get("/api/sample-summary/{sample_id}")
def get_sample_summary(sample_id: int, refresh: bool = False, model: str = DEFAULT_MODEL) -> dict:
    try:
        summary, context = _ensure_sample_summary(sample_id, model=model, refresh=refresh)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")
    return {"summary": clean_summary(summary).model_dump(), **context}


@app.post("/api/sample-chat/{sample_id}")
async def post_sample_chat(sample_id: int, request: Request) -> dict:
    """Single-case chat. Body: {messages: [{role, content}, ...], model?}.
    Requires the sample to have already been summarised (bundle, summary,
    and context cached on disk); 400 if not."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON body")
    messages = body.get("messages") or []
    if not isinstance(messages, list) or not messages:
        raise HTTPException(status_code=400, detail="messages must be a non-empty list")
    for m in messages:
        if not isinstance(m, dict) or m.get("role") not in ("user", "assistant"):
            raise HTTPException(status_code=400, detail="each message needs role=user|assistant")
        if not isinstance(m.get("content"), str):
            raise HTTPException(status_code=400, detail="message content must be a string")
    if messages[-1]["role"] != "user":
        raise HTTPException(status_code=400, detail="last message must be from the user")

    bp = _sample_bundle_path(sample_id)
    sp = _sample_summary_path(sample_id)
    cp = _sample_context_path(sample_id)
    if not (bp.exists() and sp.exists() and cp.exists()):
        raise HTTPException(
            status_code=400,
            detail=f"sample {sample_id} not summarised yet — open the case to generate it first",
        )
    try:
        bundle = CaseBundle.model_validate_json(bp.read_text())
        summary = CaseSummary.model_validate_json(sp.read_text())
        context = json.loads(cp.read_text())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"cache read failed: {type(e).__name__}: {e}")

    model = body.get("model") or CHAT_DEFAULT_MODEL
    try:
        reply = chat_about_sample(
            messages, bundle=bundle, summary=summary, context=context, model=model,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")
    return {"reply": reply, "model": model}


@app.post("/api/run/{run_id}/prewarm")
def prewarm_run(run_id: int, model: str = DEFAULT_MODEL) -> dict:
    """Kick off summarisation for every sample in the run on background threads.
    Returns immediately with the list of sample ids being processed."""
    samples = list_run_samples(run_id).get("samples", [])
    import threading
    started: list[int] = []
    for s in samples:
        if _sample_summary_path(s["id"]).exists():
            continue
        sid = int(s["id"])
        started.append(sid)
        threading.Thread(
            target=_ensure_sample_summary,
            args=(sid,),
            kwargs={"model": model},
            daemon=True,
        ).start()
    return {"run_id": run_id, "started": started, "already_cached": len(samples) - len(started)}


@app.get("/api/interpretations")
def list_interpretations() -> dict:
    client = _get_client()
    interps = client.search_interpretations(limit=200)
    out = []
    for i in interps:
        out.append({
            "id": i["id"],
            "name": i.get("name"),
            "status": i.get("status"),
            "analysis_id": i.get("analysisId"),
            "created_at": i.get("createdAt"),
            "edited_at": i.get("editedAt"),
            "etag": i.get("etag"),
            "has_summary": _summary_path(i["id"]).exists(),
        })
    return {"interpretations": out}


@app.get("/api/summary/{interpretation_id}")
def get_summary(interpretation_id: str, refresh: bool = False, model: str = DEFAULT_MODEL) -> dict:
    try:
        summary = _ensure_summary(interpretation_id, model=model, refresh=refresh)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")
    return clean_summary(summary).model_dump()


@app.post("/api/summary/{interpretation_id}/refresh")
def refresh_summary(interpretation_id: str, model: str = DEFAULT_MODEL) -> dict:
    try:
        summary = _ensure_summary(interpretation_id, model=model, refresh=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")
    return summary.model_dump()


@app.get("/api/summaries")
def list_summaries() -> dict:
    """Return everything we have cached on disk, joined with interpretation metadata."""
    client = _get_client()
    interps = client.search_interpretations(limit=200)
    interp_by_id = {i["id"]: i for i in interps}

    out = []
    for path in sorted(BUILD_DIR.glob("interpretation-*.summary.json")):
        interp_id = path.stem.replace(".summary", "")
        s = _read_summary(interp_id)
        if s is None:
            continue
        meta = interp_by_id.get(interp_id, {})
        # Try to peek at sample info from the bundle.
        sample_user_ref = None
        panel_label = None
        bundle_path = _bundle_path(interp_id)
        if bundle_path.exists():
            try:
                b = CaseBundle.model_validate_json(bundle_path.read_text())
                sample_user_ref = b.sample.sample_user_ref
                panel_label = b.sample.panel_label
            except Exception:
                pass
        out.append({
            "interpretation_id": interp_id,
            "name": meta.get("name"),
            "status": meta.get("status"),
            "edited_at": meta.get("editedAt"),
            "sample_user_ref": sample_user_ref,
            "panel_label": panel_label,
            "summary": s.model_dump(),
        })

    # Sort: HIGH first, then MEDIUM, then LOW; FAIL before WARN before PASS within each.
    priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    qc_order = {"FAIL": 0, "WARN": 1, "PASS": 2}
    out.sort(
        key=lambda r: (
            priority_order.get(r["summary"]["priority"], 9),
            qc_order.get(r["summary"]["qc_status"], 9),
            r["interpretation_id"],
        )
    )
    return {"summaries": out}


# ---- HTML fallback ----


@app.get("/", response_class=HTMLResponse)
def index_page(request: Request) -> HTMLResponse:
    p = TEMPLATES_DIR / "triage.html"
    if not p.exists():
        return HTMLResponse(
            "<h1>Smart Case Summary backend running</h1>"
            "<p>API: <a href='/api/summaries'>/api/summaries</a> · "
            "<a href='/api/interpretations'>/api/interpretations</a></p>",
            status_code=200,
        )
    return HTMLResponse(p.read_text(), status_code=200)


def main() -> int:
    """`python -m src.llm_report.api` runs uvicorn."""
    import uvicorn
    uvicorn.run(
        "src.llm_report.api:app",
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "8000")),
        reload=False,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
