"""
Draft the clinical report from a CaseBundle using Claude with strict tool_use.

Architecture:
  - System prompt + glossary are cached (5 min TTL) so iteration stays cheap.
  - Variant set is pre-filtered by ranker.is_actionable; the LLM only sees
    actionable evidence cards plus aggregate skipped counts.
  - Output is a typed ReportDraft; Claude is forced to fill the
    submit_clinical_report_draft tool, no free-form text. We extract the tool
    input and validate via Pydantic.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from anthropic import Anthropic

from .case_bundle import CaseBundle, VariantEvidence
from .ranker import RankedFindings, rank_findings
from .report_draft import ReportDraft, report_draft_tool_schema

DEFAULT_MODEL = "claude-opus-4-7"
DEFAULT_MAX_TOKENS = 4096

SYSTEM_PROMPT = (
    "You are an assistant to a board-certified molecular genetic pathologist. "
    "You draft the interpretation portion of a clinical genomic report from "
    "the structured case bundle provided. The pathologist will edit and sign "
    "off; your draft is a starting point that must be auditable.\n\n"

    "Hard rules — follow these without exception:\n"
    "  1. Use only values that appear in the case bundle. Do not invent gene "
    "     symbols, HGVS strings, classifications, percentages, or counts.\n"
    "  2. When you reference a value in prose, that value must appear verbatim "
    "     in the bundle (HGVS strings, gene symbols, percentages, ABCD label, "
    "     ClinVar status, etc.). Round VAF and frequencies only to the precision "
    "     present in the bundle.\n"
    "  3. Cite the bundle fields you used in the cites_fields list per finding. "
    "     If you did not use a field, do not include it.\n"
    "  4. Refer to the patient/sample only by the bundle's sample_user_ref. "
    "     Do not assert clinical phenotype or family history that is not in "
    "     the bundle.\n"
    "  5. Output is via the submit_clinical_report_draft tool only. "
    "     Do not return free-form text outside the tool call.\n"
    "  6. Style: terse, factual, neutral. No marketing language, no "
    "     reassurance, no recommendations beyond what the evidence supports. "
    "     Avoid em dashes; use commas, periods, or parentheses."
)

GLOSSARY = (
    "Glossary used in case bundles:\n"
    "- ACMG classification: Pathogenic, Likely_pathogenic, VUS (variant of "
    "  unknown significance), Likely_benign, Benign. Use the value verbatim.\n"
    "- ABCD: SOPHiA's in-house pathogenicity predictor. A = highest "
    "  pathogenicity confidence, D = lowest. Treat A/B/C as actionable, "
    "  D as low-priority.\n"
    "- ClinVar CLNSIG: external classification. 'Conflicting_classifications_"
    "  of_pathogenicity' means submitters disagreed; flag as a discrepancy "
    "  when ACMG says otherwise.\n"
    "- VAF (allele frequency): percentage of reads supporting the variant. "
    "  ~50% = heterozygous in a germline sample, ~100% = homozygous, ~0% may "
    "  indicate noise.\n"
    "- gnomAD AF: population frequency. >1% (0.01) usually argues against "
    "  pathogenicity for rare-disease alleles.\n"
    "- in_report (boolean): pathologist already flagged this variant for "
    "  inclusion in the signed report.\n"
    "- HGVS c. (cnomen.base): coding-sequence change. p. (pnomen.hgvsRefSeq): "
    "  protein change. Use both when present."
)

ACMG_HINT = (
    "When gene_symbol is null and consequence is 'intergenic', the variant has "
    "no clear gene context. Mention the locus only briefly and recommend "
    "low-priority confirmation."
)


@dataclass(frozen=True)
class DrafterUsage:
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int


def _variant_to_evidence_card(v: VariantEvidence) -> dict:
    """Compact JSON projection the LLM consumes. Keep field names stable —
    they are part of the citation contract."""
    return {
        "sg_id": v.sg_id,
        "gene_symbol": v.gene_symbol,
        "transcript_name": v.transcript_name,
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


def _build_user_message(
    bundle: CaseBundle, ranked: RankedFindings
) -> list[dict]:
    """User message content blocks. The constant glossary is cached; the
    case-specific payload is fresh each call."""
    case_payload = {
        "interpretation": {
            "id": bundle.interpretation_id,
            "name": bundle.interpretation_name,
            "status": bundle.interpretation_status,
        },
        "sample": {
            "sample_user_ref": bundle.sample.sample_user_ref,
            "panel_label": bundle.sample.panel_label,
            "reference_genome": bundle.sample.reference_genome,
            "experiment_type": bundle.sample.experiment_type,
            "run_user_ref": bundle.sample.run_user_ref,
        },
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
        "actionable_variants": [
            _variant_to_evidence_card(v) for v in ranked.actionable
        ],
        "skipped_summary": {
            "total_in_panel_PASS": bundle.variant_count,
            "actionable_count": len(ranked.actionable),
            "skipped_by_acmg_class": ranked.skipped_summary,
            "explanation": (
                "Variants with ACMG = Benign or Likely_benign and no "
                "conflicting ClinVar are excluded from this draft."
            ),
        },
    }

    return [
        {
            "type": "text",
            "text": GLOSSARY + "\n\n" + ACMG_HINT,
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": (
                "Case bundle for drafting:\n\n```json\n"
                + json.dumps(case_payload, indent=2)
                + "\n```\n\nProduce the report draft now via the "
                "submit_clinical_report_draft tool."
            ),
        },
    ]


def draft_report(
    bundle: CaseBundle,
    *,
    model: str = DEFAULT_MODEL,
    client: Anthropic | None = None,
) -> tuple[ReportDraft, DrafterUsage]:
    if client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Export it in your shell."
            )
        client = Anthropic()

    ranked = rank_findings(bundle)
    user_blocks = _build_user_message(bundle, ranked)

    response = client.messages.create(
        model=model,
        max_tokens=DEFAULT_MAX_TOKENS,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=[report_draft_tool_schema()],
        tool_choice={"type": "tool", "name": "submit_clinical_report_draft"},
        messages=[{"role": "user", "content": user_blocks}],
    )

    tool_call = next(
        (b for b in response.content if getattr(b, "type", None) == "tool_use"),
        None,
    )
    if tool_call is None:
        raise RuntimeError(
            f"Claude returned no tool_use block. stop_reason={response.stop_reason} "
            f"content_types={[getattr(b,'type',None) for b in response.content]}"
        )

    draft = ReportDraft.model_validate(tool_call.input)

    usage = DrafterUsage(
        input_tokens=getattr(response.usage, "input_tokens", 0) or 0,
        output_tokens=getattr(response.usage, "output_tokens", 0) or 0,
        cache_read_tokens=getattr(response.usage, "cache_read_input_tokens", 0) or 0,
        cache_creation_tokens=getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
    )
    return draft, usage
