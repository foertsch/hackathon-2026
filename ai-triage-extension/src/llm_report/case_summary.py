"""
CaseSummary — the structured triage card surfaced beside each pending case.

The card has two halves:

  - DETERMINISTIC: priority, qc_status, the choice of which variants and
    aggregates fill which slot, plus the templated text for the top_finding
    and secondary_finding slots. Computed from typed fields in `ranker.py`.
    No LLM judgement, no glossary interpretation.

  - LLM: the headline, plus the prose for the volume_note and
    discrepancy_note slots. The LLM receives a structured input per slot
    and writes ≤140-char prose against it. The verifier checks every
    value-bearing token in those slots against the cited evidence.

Each BulletSlot binds the variants / fields it claims to draw from, so
hover-to-trace can light up exactly the source data for any sentence.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Priority = Literal["HIGH", "MEDIUM", "LOW"]
QCStatus = Literal["PASS", "WARN", "FAIL"]
SlotName = Literal["top_finding", "secondary_finding", "volume_note", "discrepancy_note"]

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
    "qc_indicator",
    "panel_label",
    "experiment_type",
]


class BulletSlot(BaseModel):
    """One line in the AI card. Always rendered if present; missing slots
    are omitted (slot order is fixed by ``SlotName``)."""

    model_config = ConfigDict(extra="forbid")

    slot: SlotName
    text: str = Field(..., max_length=200)
    cites_sg_id: Optional[str] = Field(
        None,
        description="The variant this bullet primarily draws from (for "
        "top_finding / secondary_finding). Null for aggregates.",
    )
    cites_sg_ids: list[str] = Field(
        default_factory=list,
        description="Multi-variant aggregate slots (discrepancy_note) list "
        "every variant they reference here.",
    )
    cites_fields: list[EvidenceField] = Field(
        default_factory=list,
        description="Bundle field names whose values appear in `text`. "
        "Used by the verifier to check every value-bearing token.",
    )
    auto_generated: bool = Field(
        False,
        description="True for templated slots (top_finding, secondary_finding) "
        "whose text was assembled deterministically from the variant card. "
        "False for LLM-authored slots.",
    )


class CaseSummary(BaseModel):
    """The full card payload. priority / qc_status are deterministic and
    set by the API layer from ``ranker.rank_findings``; the LLM only fills
    headline + prose for the LLM slots."""

    model_config = ConfigDict(extra="forbid")

    priority: Priority
    qc_status: QCStatus
    headline: str = Field(..., max_length=200)
    bullets: list[BulletSlot] = Field(default_factory=list)


def case_summary_tool_schema() -> dict:
    """Anthropic tool definition for the summary drafter."""
    return {
        "name": "submit_case_summary",
        "description": (
            "Submit a 4-5 bullet triage summary for the interpretation. The "
            "summary appears on the analysis index page and must be glanceable. "
            "Every value referenced in prose MUST appear verbatim in the "
            "provided case bundle. Do not invent gene symbols, HGVS strings, "
            "classifications, percentages, or counts."
        ),
        "input_schema": CaseSummary.model_json_schema(),
    }
