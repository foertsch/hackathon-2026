"""
Deterministic prose generation for the variant slots (top_finding,
secondary_finding). No LLM. Each slot produces a BulletSlot whose `text` is
mechanically assembled from the chosen VariantEvidence and whose
provenance fields name exactly the evidence-card columns that contributed.

Empty-field handling: if a value is null/missing we drop that segment from
the template rather than write 'unknown' or 'N/A'. The bullet stays short
and honest.
"""

from __future__ import annotations

from typing import Optional

from .case_bundle import VariantEvidence
from .case_summary import BulletSlot

# The set of fields a variant slot ever cites. Used by the verifier to know
# which columns to look at when checking value-bearing tokens.
_VARIANT_TEMPLATE_FIELDS = (
    "gene_symbol",
    "hgvs_c",
    "hgvs_p",
    "chromosome",
    "acmg_classification",
    "clinvar_significance",
    "abcd_label",
)


def _strip_paren_around_pdot(p: Optional[str]) -> Optional[str]:
    """`NP_000042.3:p.(Ser99Gly)` → `p.(Ser99Gly)`. Take only the protein
    portion of an HGVS p. value so the bullet stays compact."""
    if not p:
        return None
    if ":p." in p:
        return p.split(":", 1)[1]
    return p


def _variant_label(v: VariantEvidence) -> str:
    """`{gene} {hgvs_c} ({hgvs_p})` or `chr{n} {hgvs_c}` if gene is null."""
    parts: list[str] = []
    if v.gene_symbol:
        parts.append(v.gene_symbol)
    elif v.chromosome:
        parts.append(v.chromosome)
    if v.hgvs_c:
        parts.append(v.hgvs_c)
    out = " ".join(parts) if parts else (v.sg_id or "variant")
    p_short = _strip_paren_around_pdot(v.hgvs_p)
    if p_short and "(" in p_short:
        out += f" ({p_short.split('(', 1)[1].rstrip(')')})"
    elif p_short:
        out += f" ({p_short})"
    return out


def _evidence_segments(v: VariantEvidence) -> tuple[list[str], list[str]]:
    """Build the right-hand evidence segments and the list of fields used."""
    segments: list[str] = []
    fields_used: list[str] = []
    if v.acmg_classification:
        segments.append(f"ACMG {v.acmg_classification}")
        fields_used.append("acmg_classification")
    if v.clinvar_significance:
        segments.append(f"ClinVar {v.clinvar_significance}")
        fields_used.append("clinvar_significance")
    if v.abcd_label:
        segments.append(f"ABCD {v.abcd_label}")
        fields_used.append("abcd_label")
    return segments, fields_used


def make_variant_slot(slot_name: str, v: Optional[VariantEvidence]) -> Optional[BulletSlot]:
    """Top or secondary finding bullet — deterministic template, no LLM."""
    if v is None:
        return None
    label = _variant_label(v)
    segments, ev_fields = _evidence_segments(v)
    text = label
    if segments:
        text += " — " + ", ".join(segments) + "."
    else:
        text = text.rstrip(".") + "."

    cites_fields: list[str] = []
    # Track which template fields actually contributed.
    if v.gene_symbol:
        cites_fields.append("gene_symbol")
    elif v.chromosome:
        cites_fields.append("chromosome")
    if v.hgvs_c:
        cites_fields.append("hgvs_c")
    if v.hgvs_p:
        cites_fields.append("hgvs_p")
    cites_fields.extend(ev_fields)

    return BulletSlot(
        slot=slot_name,
        text=text,
        cites_sg_id=v.sg_id,
        cites_sg_ids=[v.sg_id],
        cites_fields=cites_fields,
        auto_generated=True,
    )
