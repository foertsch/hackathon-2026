"""
Build a CaseSummary from a CaseBundle.

The pipeline is deterministic everywhere except the small set of prose strings
the LLM is uniquely good at:

  1. ``ranker.rank_findings(bundle)`` — picks actionable variants, computes
     priority + qc_status from typed fields, finds ACMG/ClinVar discrepancies.
  2. ``bullet_templates.make_variant_slot(...)`` — deterministically composes
     the top_finding and secondary_finding bullet text from the chosen
     variant's evidence card. No LLM here.
  3. LLM call — receives a compact, structured payload (priority, top/secondary
     summaries, volume aggregate, discrepancy list) and writes only:
        - headline (one ≤120 char sentence)
        - volume_note  (one ≤140 char sentence)
        - discrepancy_note (one ≤140 char sentence, or null if no discrepancies)
  4. Final CaseSummary is composed from the deterministic + LLM outputs. The
     LLM never sets priority / qc_status / which variants the slots cite.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from anthropic import Anthropic
from pydantic import BaseModel, ConfigDict, Field

from ._gemini_compat import to_gemini_schema
from .bullet_templates import make_variant_slot
from .case_bundle import CaseBundle, VariantEvidence
from .case_summary import BulletSlot, CaseSummary
from .ranker import Discrepancy, RankedFindings, rank_findings

DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_MAX_TOKENS = 1024


# ---- LLM schema (just the prose pieces) -------------------------------------


class _LLMParts(BaseModel):
    """The LLM's only job: three short strings.

    headline                — ≤120 chars, the single most important takeaway.
    volume_note             — ≤140 chars, narrates panel/actionable counts.
    discrepancy_note        — ≤140 chars, narrates ACMG/ClinVar disagreements;
                              null if discrepancies list is empty.
    """

    model_config = ConfigDict(extra="forbid")

    headline: str = Field(..., max_length=200)
    volume_note: str = Field(..., max_length=200)
    discrepancy_note: Optional[str] = Field(None, max_length=200)


def _llm_parts_tool_schema() -> dict:
    return {
        "name": "submit_card_text",
        "description": (
            "Write the three short prose pieces of the AI triage card. The "
            "structured fields (priority, slot variants, counts) are computed "
            "deterministically and given as input — do not restate them, just "
            "narrate them concisely."
        ),
        "input_schema": _LLMParts.model_json_schema(),
    }


# ---- Prompts ----------------------------------------------------------------


SYSTEM_PROMPT = (
    "You write three short prose strings for a triage card shown to a "
    "molecular pathologist:\n"
    "  1. headline — the case in one sentence (≤120 chars).\n"
    "  2. volume_note — actionable count vs panel total (≤140 chars).\n"
    "  3. discrepancy_note — list ACMG/ClinVar disagreements; null if the "
    "input list is empty.\n\n"
    "Rules:\n"
    "  - Use only values present in the input. No invented genes, HGVS, "
    "    classifications, percentages, or counts.\n"
    "  - Style: terse, factual, neutral. No marketing, no reassurance, no "
    "    clinical recommendations beyond what the evidence supports. Avoid "
    "    em dashes; use commas, periods, or parentheses.\n"
    "  - Do NOT restate facts already in the structured input. Specifically: "
    "    do not name the panel, experiment_type, or that QC passed — those "
    "    are surfaced in the surrounding UI. Mention QC only when failed.\n"
    "  - The TOP and SECONDARY findings are templated separately — do NOT "
    "    repeat their HGVS strings or classifications in the headline; the "
    "    headline summarises the case, not the variant."
)


# ---- Build the LLM input ----------------------------------------------------


def _variant_summary(v: Optional[VariantEvidence]) -> Optional[dict]:
    if v is None:
        return None
    return {
        "sg_id": v.sg_id,
        "gene_symbol": v.gene_symbol,
        "chromosome": v.chromosome,
        "hgvs_c": v.hgvs_c,
        "hgvs_p": v.hgvs_p,
        "acmg_classification": v.acmg_classification,
        "clinvar_significance": v.clinvar_significance,
        "abcd_label": v.abcd_label,
    }


def _discrepancy_summary(d: Discrepancy) -> dict:
    return {
        "sg_id": d.variant.sg_id,
        "gene": d.variant.gene_symbol,
        "hgvs_c": d.variant.hgvs_c,
        "acmg": d.acmg,
        "clinvar": d.clinvar,
        "direction": d.direction,
    }


def _build_llm_input(bundle: CaseBundle, ranked: RankedFindings) -> dict:
    actionable = ranked.actionable
    top = actionable[0] if len(actionable) >= 1 else None
    secondary = actionable[1] if len(actionable) >= 2 else None
    return {
        "priority": ranked.priority,
        "qc_status": ranked.qc_status,
        "top_finding": _variant_summary(top),
        "secondary_finding": _variant_summary(secondary),
        "volume": {
            "actionable_count": len(actionable),
            "total_pass": bundle.variant_count,
            "skipped_by_class": ranked.skipped_summary,
        },
        "discrepancies": [_discrepancy_summary(d) for d in ranked.discrepancies],
    }


# ---- LLM call ---------------------------------------------------------------


@dataclass(frozen=True)
class SummarizerUsage:
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int


def _is_gemini(model: str) -> bool:
    return model.startswith("gemini")


def _call_llm_gemini(payload: dict, model: str) -> tuple[_LLMParts, SummarizerUsage]:
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY / GOOGLE_API_KEY is not set.")
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    schema = to_gemini_schema(_LLMParts.model_json_schema())
    user_text = (
        "Card input (deterministic — do not restate, just narrate):\n\n```json\n"
        + json.dumps(payload, indent=2)
        + "\n```\n\nReturn the three prose strings as JSON."
    )
    last_err: Exception | None = None
    max_attempts = 5
    for attempt in range(max_attempts):
        try:
            # Spread temperature across attempts; some inputs deterministically
            # truncate at temp=0 but succeed at slight noise.
            temperature = min(0.0 + attempt * 0.2, 0.7)
            response = client.models.generate_content(
                model=model,
                contents=[user_text],
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=temperature,
                    max_output_tokens=DEFAULT_MAX_TOKENS,
                    response_mime_type="application/json",
                    response_schema=schema,
                ),
            )
            cand = (response.candidates or [None])[0]
            if not cand or not cand.content or not cand.content.parts:
                raise RuntimeError(
                    f"Gemini empty content. finish_reason={getattr(cand, 'finish_reason', None)}"
                )
            text = "".join((p.text or "") for p in cand.content.parts if hasattr(p, "text"))
            parsed = json.loads(text)
            parts = _LLMParts.model_validate(parsed)
            um = response.usage_metadata
            usage = SummarizerUsage(
                input_tokens=getattr(um, "prompt_token_count", 0) or 0,
                output_tokens=getattr(um, "candidates_token_count", 0) or 0,
                cache_read_tokens=getattr(um, "cached_content_token_count", 0) or 0,
                cache_creation_tokens=0,
            )
            if attempt > 0:
                print(f"   (gemini retry succeeded on attempt {attempt + 1})")
            return parts, usage
        except Exception as e:
            last_err = e
            if attempt < max_attempts - 1:
                print(f"   gemini attempt {attempt + 1} failed: {type(e).__name__}: {str(e)[:160]}")
            continue
    raise RuntimeError(f"Gemini failed after {max_attempts} attempts: {last_err}")


def _call_llm_claude(payload: dict, model: str) -> tuple[_LLMParts, SummarizerUsage]:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY is not set.")
    client = Anthropic()
    user_text = (
        "Card input (deterministic — do not restate, just narrate):\n\n```json\n"
        + json.dumps(payload, indent=2)
        + "\n```"
    )
    response = client.messages.create(
        model=model,
        max_tokens=DEFAULT_MAX_TOKENS,
        system=[
            {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
        ],
        tools=[_llm_parts_tool_schema()],
        tool_choice={"type": "tool", "name": "submit_card_text"},
        messages=[{"role": "user", "content": user_text}],
    )
    tool_call = next(
        (b for b in response.content if getattr(b, "type", None) == "tool_use"), None
    )
    if tool_call is None:
        raise RuntimeError("Claude returned no tool_use block.")
    parts = _LLMParts.model_validate(tool_call.input)
    usage = SummarizerUsage(
        input_tokens=getattr(response.usage, "input_tokens", 0) or 0,
        output_tokens=getattr(response.usage, "output_tokens", 0) or 0,
        cache_read_tokens=getattr(response.usage, "cache_read_input_tokens", 0) or 0,
        cache_creation_tokens=getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
    )
    return parts, usage


# ---- Compose final CaseSummary ----------------------------------------------


def _compose_bullets(
    ranked: RankedFindings, parts: _LLMParts, payload: dict
) -> list[BulletSlot]:
    slots: list[BulletSlot] = []
    actionable = ranked.actionable
    top = make_variant_slot("top_finding", actionable[0] if len(actionable) >= 1 else None)
    if top:
        slots.append(top)
    secondary = make_variant_slot(
        "secondary_finding", actionable[1] if len(actionable) >= 2 else None
    )
    if secondary:
        slots.append(secondary)
    slots.append(BulletSlot(
        slot="volume_note",
        text=parts.volume_note.strip(),
        cites_fields=[],  # aggregate; verifier uses payload["volume"] instead
        auto_generated=False,
    ))
    if ranked.discrepancies and parts.discrepancy_note:
        slots.append(BulletSlot(
            slot="discrepancy_note",
            text=parts.discrepancy_note.strip(),
            cites_sg_ids=[d.variant.sg_id for d in ranked.discrepancies],
            cites_fields=[
                "gene_symbol", "acmg_classification", "clinvar_significance",
                "hgvs_c", "hgvs_p",  # the LLM often quotes HGVS for specificity
            ],
            auto_generated=False,
        ))
    return slots


def summarize_case(
    bundle: CaseBundle,
    *,
    model: str = DEFAULT_MODEL,
) -> tuple[CaseSummary, SummarizerUsage]:
    ranked = rank_findings(bundle)
    payload = _build_llm_input(bundle, ranked)
    parts, usage = (
        _call_llm_gemini(payload, model)
        if _is_gemini(model)
        else _call_llm_claude(payload, model)
    )
    bullets = _compose_bullets(ranked, parts, payload)
    summary = CaseSummary(
        priority=ranked.priority,
        qc_status=ranked.qc_status,
        headline=parts.headline.strip(),
        bullets=bullets,
    )
    return summary, usage
