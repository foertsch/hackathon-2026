"""
Single-case chat: free-form Q&A over one cached sample's evidence.

The chatbot sees the same data the AI triage card was built from — the
CaseBundle (typed variants, QC, sample header) plus the deterministic
CaseSummary. It does NOT have access to other samples, runs, or the full
LAYER2 dataset; questions outside its scope should be deflected.

Trust model (MVP): the chatbot is asked to cite sg_id (or gene + HGVS)
when making variant-specific claims, and to refuse on data outside the
bundle. There is no token-level verifier on chat replies — the UI labels
the panel as an assistant whose claims must be verified clinically.
"""

from __future__ import annotations

import json
import os

from .case_bundle import CaseBundle, VariantEvidence
from .case_summary import CaseSummary

DEFAULT_MODEL = os.environ.get("CHAT_MODEL", "gemini-2.5-flash")
DEFAULT_MAX_TOKENS = 1024


SYSTEM_PROMPT = (
    "You are a chat assistant for a molecular pathologist reviewing a single "
    "genomic case in SOPHiA DDM. The pathologist has just opened the case in "
    "Gen2 and sees an AI triage card with priority, headline, and bullet "
    "findings. You answer questions about the case using ONLY the structured "
    "evidence in the provided case bundle and triage summary.\n\n"
    "Rules:\n"
    "  - When making a variant-specific claim, cite the variant by gene + "
    "HGVS, or by sg_id in brackets like [sg_xxxxx]. The pathologist uses "
    "these to trace back to the source row.\n"
    "  - Use only values present in the bundle. Do not invent gene symbols, "
    "HGVS strings, classifications, percentages, or counts. If the bundle "
    "does not contain a value the user asks about, say so explicitly.\n"
    "  - If asked about other samples, runs, or data outside this case, "
    "explain that you only have access to this case and suggest what the "
    "pathologist could check in Gen2 directly.\n"
    "  - Style: terse, factual, neutral. Two to four sentences typical. No "
    "clinical recommendations beyond what the evidence supports. Avoid em "
    "dashes; use commas, periods, or parentheses.\n"
    "  - Do not restate facts already on screen (panel name, experiment "
    "type, sample id) unless directly asked."
)


def _compact_variant(v: VariantEvidence) -> dict:
    """Per-variant payload for chat. Drops fields the chat doesn't reason
    over (provenance, transcript_version, in_exon details) to keep context
    small while preserving every clinically relevant value."""
    return {
        "sg_id": v.sg_id,
        "gene_symbol": v.gene_symbol,
        "transcript_name": v.transcript_name,
        "in_mane": v.in_mane,
        "chromosome": v.chromosome,
        "variant_type": v.variant_type,
        "consequence": v.consequence,
        "hgvs_c": v.hgvs_c,
        "hgvs_p": v.hgvs_p,
        "vaf_pct": v.vaf_pct,
        "read_depth": v.read_depth,
        "gnomad_genomes_af": v.gnomad_genomes_af,
        "gnomad_exomes_af": v.gnomad_exomes_af,
        "clinvar_significance": v.clinvar_significance,
        "clinvar_review_status": v.clinvar_review_status,
        "abcd_label": v.abcd_label,
        "acmg_classification": v.acmg_classification,
        "acmg_score": v.acmg_score,
        "in_report": v.in_report,
        "is_false_positive": v.is_false_positive,
        "user_pathogenicity": v.user_pathogenicity,
    }


def build_chat_context(
    bundle: CaseBundle, summary: CaseSummary, context: dict
) -> dict:
    """The structured payload the chat LLM sees on every turn."""
    return {
        "sample": {
            "sample_user_ref": bundle.sample.sample_user_ref,
            "panel_label": bundle.sample.panel_label,
            "experiment_type": bundle.sample.experiment_type,
            "reference_genome": bundle.sample.reference_genome,
        },
        "qc_indicators": context.get("qc_indicators", []),
        "triage_summary": {
            "priority": summary.priority,
            "qc_status": summary.qc_status,
            "headline": summary.headline,
            "bullets": [
                {
                    "slot": b.slot,
                    "text": b.text,
                    "cites_sg_id": b.cites_sg_id,
                    "auto_generated": b.auto_generated,
                }
                for b in summary.bullets
            ],
        },
        "variants_total": bundle.variant_count,
        "variants": [_compact_variant(v) for v in bundle.variants],
    }


def _is_gemini(model: str) -> bool:
    return model.startswith("gemini")


def _chat_gemini(payload: dict, messages: list[dict], model: str) -> str:
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY / GOOGLE_API_KEY is not set.")
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)

    # Inject the case payload as the first user-turn so it sits at the top
    # of context. The pretend-model ack keeps the alternation valid before
    # the real chat starts.
    contents: list[dict] = [
        {
            "role": "user",
            "parts": [{
                "text": (
                    "Case bundle (read-only — answer questions against it; "
                    "do not restate it):\n\n```json\n"
                    + json.dumps(payload, indent=2)
                    + "\n```"
                )
            }],
        },
        {
            "role": "model",
            "parts": [{"text": "Got it. Ask away."}],
        },
    ]
    for m in messages:
        role = "model" if m["role"] == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": m["content"]}]})

    response = client.models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.2,
            max_output_tokens=DEFAULT_MAX_TOKENS,
        ),
    )
    cand = (response.candidates or [None])[0]
    if not cand or not cand.content or not cand.content.parts:
        raise RuntimeError(
            f"Gemini empty content. finish_reason={getattr(cand, 'finish_reason', None)}"
        )
    text = "".join((p.text or "") for p in cand.content.parts if hasattr(p, "text"))
    return text.strip()


def _chat_claude(payload: dict, messages: list[dict], model: str) -> str:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY is not set.")
    from anthropic import Anthropic

    client = Anthropic()
    # Pin the bundle in the system block with cache_control so multi-turn
    # chats hit the prompt cache after the first request.
    sys_blocks = [
        {"type": "text", "text": SYSTEM_PROMPT},
        {
            "type": "text",
            "text": (
                "Case bundle (read-only context):\n\n"
                + json.dumps(payload, indent=2)
            ),
            "cache_control": {"type": "ephemeral"},
        },
    ]
    api_messages = [{"role": m["role"], "content": m["content"]} for m in messages]
    response = client.messages.create(
        model=model,
        max_tokens=DEFAULT_MAX_TOKENS,
        system=sys_blocks,
        messages=api_messages,
    )
    text_blocks = [
        b.text for b in response.content if getattr(b, "type", None) == "text"
    ]
    if not text_blocks:
        raise RuntimeError("Claude returned no text block.")
    return "\n".join(text_blocks).strip()


def chat_about_sample(
    messages: list[dict],
    *,
    bundle: CaseBundle,
    summary: CaseSummary,
    context: dict,
    model: str = DEFAULT_MODEL,
) -> str:
    """Run one turn of the case chat. Returns the assistant's text reply.

    `messages` is the full chat history as
    `[{role: 'user'|'assistant', content: str}, ...]`
    and must end with a user message.
    """
    if not messages or messages[-1].get("role") != "user":
        raise ValueError("messages must end with a user turn")
    payload = build_chat_context(bundle, summary, context)
    if _is_gemini(model):
        return _chat_gemini(payload, messages, model)
    return _chat_claude(payload, messages, model)
