"""
ReportDraft schema — the typed output the LLM is forced to produce via
Claude tool_use. Every claim ties back to one or more variants and a list
of bundle field names that justify it. Field names use the VariantEvidence
attribute names (e.g. "hgvs_c", "vaf_pct"), not VQS column paths — translation
to provenance happens via VARIANT_PROVENANCE in case_bundle.py.

The verifier (next phase) will check: for every value-bearing token in
`interpretation` / `recommendation` / `summary`, the value appears verbatim
in the bundle for one of the cited sg_ids.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

EvidenceField = Literal[
    "gene_symbol",
    "transcript_name",
    "chromosome",
    "variant_type",
    "consequence",
    "hgvs_c",
    "hgvs_p",
    "vaf_pct",
    "read_depth",
    "gnomad_genomes_af",
    "gnomad_exomes_af",
    "clinvar_significance",
    "clinvar_review_status",
    "abcd_label",
    "acmg_classification",
    "acmg_score",
    "in_report",
    "is_false_positive",
    "user_pathogenicity",
]

ReportPriority = Literal["high", "medium", "low"]


class ActionableFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sg_ids: list[str] = Field(
        ...,
        description=(
            "The dynamic.sgId values of the variant(s) this finding refers to. "
            "Must be present in the bundle. Usually a single sg_id per finding."
        ),
        min_length=1,
    )
    gene: Optional[str] = Field(
        None,
        description="Gene symbol from the bundle (or null if intergenic).",
    )
    classification: str = Field(
        ...,
        description=(
            "ACMG classification copied verbatim from the bundle "
            "(e.g. 'VUS', 'Benign'). Do not invent classes."
        ),
    )
    priority: ReportPriority = Field(
        ...,
        description=(
            "high = needs pathologist focus / likely impacts diagnosis; "
            "medium = noteworthy but not urgent; "
            "low = low-priority confirmation."
        ),
    )
    interpretation: str = Field(
        ...,
        description=(
            "1-3 sentences. State what the variant is, why it warrants attention, "
            "and how the evidence (ABCD, ClinVar, gnomAD, ACMG score) supports the "
            "classification. Use only values present in the bundle."
        ),
        min_length=20,
        max_length=1200,
    )
    recommendation: str = Field(
        ...,
        description=(
            "1-2 sentences. What the pathologist should do next: keep monitoring, "
            "request orthogonal testing, exclude from report, etc. Be concrete."
        ),
        min_length=10,
        max_length=600,
    )
    cites_fields: list[EvidenceField] = Field(
        ...,
        description=(
            "The specific bundle field names whose values you used in the prose. "
            "List every field referenced. The verifier checks these."
        ),
        min_length=1,
    )


class ReportDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(
        ...,
        description=(
            "2-4 sentences. Headline of the case for Dr. M.: panel, sample, "
            "overall finding count, and the single most important takeaway. "
            "Reference only values present in the bundle."
        ),
        min_length=40,
        max_length=1200,
    )
    actionable_findings: list[ActionableFinding] = Field(
        ...,
        description=(
            "One entry per variant that needs pathologist attention. Order by "
            "priority (high first). Do not include benign or likely-benign rows "
            "unless the ClinVar status conflicts with the ACMG classification."
        ),
    )
    technical_notes: str = Field(
        ...,
        description=(
            "1-3 sentences on QC status (coverage uniformity, on-target %), any "
            "limitations (e.g. low coverage flag), and which classes of variants "
            "this report excluded. State QC values copied from the bundle."
        ),
        min_length=20,
        max_length=800,
    )


def report_draft_tool_schema() -> dict:
    """Anthropic tool definition for the drafter to fill in."""
    return {
        "name": "submit_clinical_report_draft",
        "description": (
            "Submit the structured draft of a genomic clinical report for "
            "pathologist review. Every value referenced in the prose MUST appear "
            "verbatim in the provided case bundle. Do not invent gene symbols, "
            "HGVS strings, classifications, or numerical values."
        ),
        "input_schema": ReportDraft.model_json_schema(),
    }
