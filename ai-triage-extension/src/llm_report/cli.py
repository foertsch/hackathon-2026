"""
Tiny CLI:
    python -m src.llm_report.cli build-bundle <interpretation-id>
        Pull a CaseBundle from Gen2 and write it to build/<interp>.json.
        Prints a one-screen summary.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .auth import get_session
from .bundle_builder import build_case_bundle
from .case_bundle import CaseBundle
from .summary_drafter import DEFAULT_MODEL, summarize_case
from .vqs_client import VQSClient

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "build"


def _load_or_build_bundle(interpretation_id: str) -> CaseBundle:
    """Load a cached bundle if present, otherwise build it."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{interpretation_id}.bundle.json"
    if path.exists():
        return CaseBundle.model_validate_json(path.read_text())
    cmd_build_bundle(interpretation_id)
    return CaseBundle.model_validate_json(path.read_text())


# Per-MTok list prices used for cost reporting only.
MODEL_PRICES = {
    "claude-opus-4-7":   {"in": 15.0,  "out": 75.0,  "cache_r": 1.50, "cache_w": 18.75},
    "claude-sonnet-4-6": {"in": 3.0,   "out": 15.0,  "cache_r": 0.30, "cache_w":  3.75},
    "gemini-2.5-flash":  {"in": 0.30,  "out": 2.50,  "cache_r": 0.075, "cache_w": 0.0},
    "gemini-2.5-pro":    {"in": 1.25,  "out": 10.0,  "cache_r": 0.31, "cache_w": 0.0},
}


def _estimate_cost(usage, model: str) -> float:
    p = MODEL_PRICES.get(model)
    if not p:
        return 0.0
    fresh_in = max(0, usage.input_tokens - usage.cache_read_tokens) * p["in"] / 1_000_000
    cache_read = usage.cache_read_tokens * p["cache_r"] / 1_000_000
    cache_write = usage.cache_creation_tokens * p["cache_w"] / 1_000_000
    out = usage.output_tokens * p["out"] / 1_000_000
    return fresh_in + cache_read + cache_write + out


def cmd_build_bundle(interpretation_id: str) -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    session = get_session()
    client = VQSClient(session)
    bundle = build_case_bundle(client, interpretation_id)

    out_path = OUT_DIR / f"{interpretation_id}.bundle.json"
    out_path.write_text(bundle.model_dump_json(indent=2))

    print(f"interpretation : {bundle.interpretation_id}  ({bundle.interpretation_name})")
    print(f"status         : {bundle.interpretation_status}  etag={bundle.interpretation_etag}")
    print(f"sample         : {bundle.sample.sample_user_ref}  ({bundle.sample.experiment_type}, {bundle.sample.reference_genome})")
    print(f"panel          : {bundle.sample.panel_label}")
    print(f"run            : {bundle.sample.run_user_ref}")
    print(f"QC indicators  : {len(bundle.qc_indicators)}")
    for q in bundle.qc_indicators[:5]:
        rng = f"[{q.range_lower}, {q.range_upper}]" if q.range_lower is not None else ""
        print(f"   {q.name:30s} {q.status:8s} {q.value!r:>10}  {rng}")
    print(f"variants       : {bundle.variant_count}")
    print(f"   ACMG:  {bundle.acmg_breakdown}")
    interesting = bundle.vus_or_pathogenic
    print(f"   VUS or worse:  {len(interesting)}")
    for v in interesting[:6]:
        print(
            f"     {v.gene_symbol or '-':10s} {v.variant_type or '-':5s} "
            f"{v.consequence or '-':14s} VAF={v.vaf_pct} DP={v.read_depth} "
            f"ABCD={v.abcd_label} ACMG={v.acmg_classification} "
            f"ClinVar={(v.clinvar_significance or '-')[:30]}"
        )
    print(f"\nwrote {out_path.relative_to(REPO_ROOT)}  ({out_path.stat().st_size:,} B)")
    return 0


def _print_summary(summary, *, header: str = "") -> None:
    if header:
        print(f"\n{header}")
    print(f"  priority : {summary.priority}     qc: {summary.qc_status}")
    print(f"  headline : {summary.headline}")
    for b in summary.bullets:
        print(f"   - {b}")
    if summary.key_finding_sg_id:
        print(f"  key sg_id: {summary.key_finding_sg_id}")
    print(f"  cites    : {len(summary.cites_sg_ids)} variants, fields={summary.cites_fields}")


def cmd_summarize_case(interpretation_id: str, *, model: str = DEFAULT_MODEL) -> int:
    bundle = _load_or_build_bundle(interpretation_id)
    print(f"summarizing {interpretation_id} with {model}...")
    summary, usage = summarize_case(bundle, model=model)

    out_path = OUT_DIR / f"{interpretation_id}.summary.json"
    out_path.write_text(summary.model_dump_json(indent=2))

    _print_summary(summary, header=f"== {interpretation_id} ==")
    print(
        f"  tokens: in={usage.input_tokens} out={usage.output_tokens} "
        f"cache_r={usage.cache_read_tokens} cache_w={usage.cache_creation_tokens}  "
        f"cost ≈ ${_estimate_cost(usage, model):.4f}"
    )
    print(f"\nwrote {out_path.relative_to(REPO_ROOT)}")
    return 0


def cmd_summarize_all(*, model: str = DEFAULT_MODEL, refresh: bool = False) -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    session = get_session()
    client = VQSClient(session)
    interps = client.search_interpretations(limit=200)
    print(f"found {len(interps)} interpretations")

    from .case_summary import CaseSummary as _CS

    rollup = []
    total_cost = 0.0
    failures: list[dict] = []
    for interp in interps:
        interp_id = interp["id"]
        summary_path = OUT_DIR / f"{interp_id}.summary.json"

        # Reuse previously-saved summary unless --refresh was passed.
        if not refresh and summary_path.exists():
            try:
                summary = _CS.model_validate_json(summary_path.read_text())
                print(f"  [{interp_id}] cached summary ({summary.priority}) — skip")
                rollup.append({
                    "interpretation_id": interp_id,
                    "name": interp.get("name"),
                    "priority": summary.priority,
                    "qc_status": summary.qc_status,
                    "headline": summary.headline,
                    "bullets": summary.bullets,
                    "key_finding_sg_id": summary.key_finding_sg_id,
                    "cost": 0.0,
                    "cached": True,
                })
                continue
            except Exception:
                pass  # corrupt; rebuild

        try:
            bundle = _load_or_build_bundle(interp_id)
        except Exception as e:
            print(f"  [{interp_id}] bundle build failed: {e}")
            failures.append({"interpretation_id": interp_id, "stage": "bundle", "error": str(e)[:200]})
            continue
        try:
            summary, usage = summarize_case(bundle, model=model)
        except Exception as e:
            print(f"  [{interp_id}] summarize failed: {type(e).__name__}: {str(e)[:160]}")
            failures.append({"interpretation_id": interp_id, "stage": "summarize", "error": str(e)[:200]})
            continue
        summary_path.write_text(summary.model_dump_json(indent=2))
        cost = _estimate_cost(usage, model)
        total_cost += cost
        rollup.append({
            "interpretation_id": interp_id,
            "name": interp.get("name"),
            "priority": summary.priority,
            "qc_status": summary.qc_status,
            "headline": summary.headline,
            "bullets": summary.bullets,
            "key_finding_sg_id": summary.key_finding_sg_id,
            "cost": round(cost, 4),
            "cached": False,
        })
        _print_summary(summary, header=f"== {interp_id}  ({interp.get('name','')}) ==")
        print(f"  cost ≈ ${cost:.4f}")

    rollup_path = OUT_DIR / "all_summaries.json"
    rollup_path.write_text(json.dumps(rollup, indent=2))
    print(f"\nwrote {rollup_path.relative_to(REPO_ROOT)}  (total cost ≈ ${total_cost:.4f})")

    # Also print a triage table sorted by priority.
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    rollup.sort(key=lambda r: (order.get(r["priority"], 9), r["interpretation_id"]))
    print("\n--- triage table ---")
    print(f"{'priority':9} {'qc':5} {'interpretation':30} {'headline'}")
    for r in rollup:
        print(f"{r['priority']:9} {r['qc_status']:5} {r['interpretation_id']:30} {r['headline']}")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(
            "usage:\n"
            "  python -m src.llm_report.cli build-bundle <interpretation-id>\n"
            "  python -m src.llm_report.cli summarize-case <interpretation-id> [--model <name>]\n"
            "  python -m src.llm_report.cli summarize-all [--model <name>]",
            file=sys.stderr,
        )
        return 2
    cmd = argv[1]
    model = DEFAULT_MODEL
    if "--model" in argv:
        i = argv.index("--model")
        model = argv[i + 1]
    if cmd == "build-bundle":
        if len(argv) < 3:
            print("missing interpretation id", file=sys.stderr)
            return 2
        return cmd_build_bundle(argv[2])
    if cmd == "summarize-case":
        if len(argv) < 3:
            print("missing interpretation id", file=sys.stderr)
            return 2
        return cmd_summarize_case(argv[2], model=model)
    if cmd == "summarize-all":
        refresh = "--refresh" in argv
        return cmd_summarize_all(model=model, refresh=refresh)
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
