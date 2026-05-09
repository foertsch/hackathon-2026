"""
Pre-filter the variant list to the cognitive-load set Dr. M. cares about,
compute a deterministic case-level priority, and select the slot inputs
the bullet writer (templated + LLM) will consume.

This module is the entire deterministic substrate of the AI card. The LLM
sees nothing the ranker hasn't approved; every priority decision is plain
Python expressed against typed evidence cards.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Optional

from .case_bundle import CaseBundle, QCIndicator, VariantEvidence

Priority = Literal["HIGH", "MEDIUM", "LOW"]
QCStatus = Literal["PASS", "WARN", "FAIL"]

ACMG_PRIORITY = {"VUS", "Likely_pathogenic", "Pathogenic"}
ACMG_HIGH = {"Pathogenic", "Likely_pathogenic"}
ABCD_PRIORITY = {"A", "B", "C"}
ABCD_HIGH = {"A", "B"}
CLINVAR_PRIORITY_KEYWORDS = (
    "Pathogenic",
    "Likely_pathogenic",
    "Conflicting",
    "Risk_factor",
)
CLINVAR_HIGH_KEYWORDS = ("Pathogenic", "Likely_pathogenic")
CLINVAR_BENIGN_KEYWORDS = ("Benign", "Likely_benign")
CLINVAR_CONFLICT_KEYWORDS = ("Conflicting", "Risk_factor")


def is_actionable(v: VariantEvidence) -> bool:
    if v.is_false_positive:
        return False
    if v.in_report:
        return True
    if v.acmg_classification in ACMG_PRIORITY:
        return True
    if v.abcd_label in ABCD_PRIORITY:
        return True
    if v.clinvar_significance:
        for kw in CLINVAR_PRIORITY_KEYWORDS:
            if kw.lower() in v.clinvar_significance.lower():
                return True
    return False


def _priority_rank(v: VariantEvidence) -> tuple:
    """Sort key — lower means higher priority (shows first)."""
    acmg_order = {"Pathogenic": 0, "Likely_pathogenic": 1, "VUS": 2}.get(
        v.acmg_classification or "", 3
    )
    abcd_order = {"A": 0, "B": 1, "C": 2, "D": 3}.get(v.abcd_label or "", 4)
    clinvar_path = (
        0 if v.clinvar_significance and "Pathogenic" in v.clinvar_significance
        else 1
    )
    in_report = 0 if v.in_report else 1
    return (in_report, acmg_order, abcd_order, clinvar_path, v.gene_symbol or "")


@dataclass(frozen=True)
class Discrepancy:
    """A variant whose ACMG and ClinVar disagree in a clinically interesting way."""

    variant: VariantEvidence
    acmg: str
    clinvar: str
    direction: Literal["acmg_softer", "acmg_stricter"]


@dataclass(frozen=True)
class RankedFindings:
    actionable: list[VariantEvidence]
    skipped_summary: dict[str, int]  # ACMG bucket -> count
    priority: Priority
    qc_status: QCStatus
    discrepancies: list[Discrepancy]


def _clinvar_contains(clinvar: Optional[str], keywords: tuple[str, ...]) -> bool:
    """Word-boundary keyword match against a ClinVar CLNSIG string.

    ClinVar values are snake_case (e.g. ``Conflicting_classifications_of_pathogenicity``).
    Naive substring matching falsely flags "Pathogenic" as present in
    "pathogenicity". We normalise underscores to spaces, then use \\b regex
    boundaries so 'Pathogenic' only matches the standalone token.
    """
    if not clinvar:
        return False
    normalized = clinvar.replace("_", " ").replace("|", " ").replace("/", " ")
    for k in keywords:
        token = k.replace("_", " ")
        if re.search(r"\b" + re.escape(token) + r"\b", normalized, re.IGNORECASE):
            return True
    return False


def compute_qc_status(qc: list[QCIndicator]) -> QCStatus:
    """All PASS → PASS; any FAIL → FAIL; any other non-PASS → WARN."""
    if not qc:
        return "PASS"
    statuses = [(q.status or "").upper() for q in qc]
    if any(s in ("FAILED", "FAIL") for s in statuses):
        return "FAIL"
    if all(s in ("PASSED", "PASS") for s in statuses):
        return "PASS"
    return "WARN"


def compute_priority(
    actionable: list[VariantEvidence], qc_status: QCStatus
) -> Priority:
    """Single source of truth for case priority. Pure function of structured
    fields — no LLM judgment, no glossary interpretation.

    HIGH if any of: in_report flagged variant; ACMG Pathogenic / Likely_pathogenic;
        ClinVar Pathogenic / Likely_pathogenic; ABCD A or B; QC failed.
    MEDIUM if any actionable variant present that isn't already HIGH (VUS,
        ABCD=C, ClinVar conflicting/risk_factor).
    LOW otherwise.
    """
    if qc_status == "FAIL":
        return "HIGH"
    for v in actionable:
        if v.in_report:
            return "HIGH"
        if v.acmg_classification in ACMG_HIGH:
            return "HIGH"
        if v.abcd_label in ABCD_HIGH:
            return "HIGH"
        if _clinvar_contains(v.clinvar_significance, CLINVAR_HIGH_KEYWORDS):
            return "HIGH"
    if actionable:
        return "MEDIUM"
    return "LOW"


def find_discrepancies(actionable: list[VariantEvidence]) -> list[Discrepancy]:
    """Variants where ACMG and ClinVar tell different stories.

    Two flavours:
      acmg_softer:   ACMG says Benign/Likely_benign but ClinVar contains
                     Pathogenic/Likely_pathogenic/Conflicting.
      acmg_stricter: ACMG says VUS/LP/P but ClinVar is Benign/Likely_benign.
    """
    out: list[Discrepancy] = []
    for v in actionable:
        if not v.clinvar_significance or not v.acmg_classification:
            continue
        clinvar_path = _clinvar_contains(v.clinvar_significance, CLINVAR_HIGH_KEYWORDS)
        clinvar_conflict = _clinvar_contains(v.clinvar_significance, CLINVAR_CONFLICT_KEYWORDS)
        clinvar_benign = _clinvar_contains(v.clinvar_significance, CLINVAR_BENIGN_KEYWORDS)
        acmg_benign = v.acmg_classification in {"Benign", "Likely_benign"}
        acmg_attentive = v.acmg_classification in {"VUS", "Likely_pathogenic", "Pathogenic"}
        if acmg_benign and (clinvar_path or clinvar_conflict):
            out.append(Discrepancy(v, v.acmg_classification, v.clinvar_significance, "acmg_softer"))
        elif acmg_attentive and clinvar_benign and not clinvar_path:
            out.append(Discrepancy(v, v.acmg_classification, v.clinvar_significance, "acmg_stricter"))
    return out


def rank_findings(bundle: CaseBundle) -> RankedFindings:
    actionable = sorted(
        (v for v in bundle.variants if is_actionable(v)),
        key=_priority_rank,
    )
    skipped: dict[str, int] = {}
    actionable_set = {v.sg_id for v in actionable}
    for v in bundle.variants:
        if v.sg_id in actionable_set:
            continue
        bucket = v.acmg_classification or "unset"
        skipped[bucket] = skipped.get(bucket, 0) + 1
    qc_status = compute_qc_status(bundle.qc_indicators)
    priority = compute_priority(actionable, qc_status)
    return RankedFindings(
        actionable=actionable,
        skipped_summary=skipped,
        priority=priority,
        qc_status=qc_status,
        discrepancies=find_discrepancies(actionable),
    )
