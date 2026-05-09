"""
Token-level verifier for AI card bullets.

Premise: every value-bearing token in LLM-authored prose must appear in the
bullet's cited evidence. Templated slots are trivially verified (their text
was assembled from cited fields). LLM slots get checked.

Token classes we care about:
  - HGVS coordinates (c. / p.)
  - Gene symbols (ALL-CAPS alphanumerics, 2..10 chars)
  - Classification phrases (Pathogenic, Likely_pathogenic, VUS, Benign,
    Likely_benign, Conflicting, Risk_factor, etc.)
  - Numbers (integers + decimals, optional %)
  - ABCD labels (single letter, only when contextually bound to "ABCD X")

Skipped (intentional):
  - Common nouns and articles ("variant", "the", "panel")
  - Sentence-level semantics ("BRCA2 is benign" with both tokens present is
    not a hallucination flag — only token presence is checked)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .case_bundle import CaseBundle, VariantEvidence
from .case_summary import BulletSlot, CaseSummary


# ---- Token patterns ----------------------------------------------------------

_HGVS_C = re.compile(r"c\.[A-Za-z0-9_+\-*>]+")
_HGVS_P = re.compile(r"p\.\([^)]+\)|p\.[A-Za-z][A-Za-z0-9*]+")
_NUMBER = re.compile(r"\b\d+(?:\.\d+)?%?\b")
# Gene symbols: 2..10 chars, all caps + digits, must contain at least one
# letter. Heuristic — gene-like tokens. Matches BRCA2, MSH3, POT1, KIT, etc.
_GENE_LIKE = re.compile(r"\b[A-Z][A-Z0-9]{1,9}\b")
# Single-letter ABCD labels are only counted when contextually bound:
_ABCD_BOUND = re.compile(r"\bABCD\s+([ABCD])\b")

CLASSIFICATION_PHRASES = [
    "Conflicting_classifications_of_pathogenicity",
    "Conflicting classifications of pathogenicity",
    "reviewed_by_expert_panel",
    "reviewed by expert panel",
    "Likely_pathogenic",
    "Likely pathogenic",
    "Likely_benign",
    "Likely benign",
    "Pathogenic",
    "Benign",
    "VUS",
    "Risk_factor",
    "Risk factor",
    "Conflicting",
]
# Words we should never treat as a "gene" or value token. The gene regex
# accepts e.g. ACMG and ABCD which are domain abbreviations, not values.
_GENE_NEGATIVES = {
    "ACMG", "ABCD", "VUS", "QC", "AI", "RUO", "IVD", "DDM",
    "HGVS", "MID", "SGID", "PMI",
}


@dataclass(frozen=True)
class VerificationResult:
    slot: str
    verified: bool
    total_tokens: int
    unverified_tokens: list[str] = field(default_factory=list)


# ---- Token extraction --------------------------------------------------------


def extract_value_tokens(text: str) -> list[str]:
    """Return distinct value-bearing tokens, in their original casing.

    Order is HGVS first (longest concrete strings) so they're stripped
    before the simpler regexes might match substrings of them.
    """
    seen: list[str] = []

    def _add(t: str):
        if t and t not in seen:
            seen.append(t)

    # Strip HGVS first so subsequent regexes don't match inside them.
    stripped = text
    for tok in _HGVS_C.findall(stripped):
        _add(tok)
        stripped = stripped.replace(tok, " " * len(tok))
    for tok in _HGVS_P.findall(stripped):
        _add(tok)
        stripped = stripped.replace(tok, " " * len(tok))

    # Classification phrases — match whole phrases (with or without spaces).
    for phrase in CLASSIFICATION_PHRASES:
        pat = re.compile(r"\b" + re.escape(phrase) + r"\b", re.IGNORECASE)
        for m in pat.finditer(stripped):
            _add(m.group(0))
        stripped = pat.sub(lambda m: " " * len(m.group(0)), stripped)

    # ABCD labels (only when contextually bound).
    for letter in _ABCD_BOUND.findall(stripped):
        _add(f"ABCD_{letter}")  # synthetic key — match against variant abcd_label

    # Gene-like tokens.
    for m in _GENE_LIKE.findall(stripped):
        if m.upper() in _GENE_NEGATIVES:
            continue
        _add(m)

    # Numbers.
    for m in _NUMBER.findall(stripped):
        _add(m)

    return seen


# ---- Bound-value collection --------------------------------------------------


def _variant_field_value(v: VariantEvidence, field_name: str) -> Optional[str]:
    val = getattr(v, field_name, None)
    if val is None:
        return None
    return str(val)


def _collect_for_variant(v: VariantEvidence, fields: list[str]) -> set[str]:
    out: set[str] = set()
    for f in fields:
        s = _variant_field_value(v, f)
        if s:
            out.add(s)
    return out


def _collect_volume_bound(bundle: CaseBundle, ranked_actionable_count: int, skipped_by_class: dict) -> set[str]:
    out: set[str] = set()
    out.add(str(bundle.variant_count))
    out.add(str(ranked_actionable_count))
    # Derived: total skipped (sum of all class counts) — the LLM often
    # narrates this number even though it's not a primitive in the input.
    skipped_total = sum((skipped_by_class or {}).values())
    out.add(str(skipped_total))
    # Derived: total minus actionable — same number, different framing.
    out.add(str(bundle.variant_count - ranked_actionable_count))
    for cls, n in (skipped_by_class or {}).items():
        out.add(str(n))
        out.add(cls)
    return out


def collect_bound_values(
    bullet: BulletSlot,
    bundle: CaseBundle,
    skipped_by_class: dict[str, int],
    actionable_count: int,
) -> set[str]:
    """Build the universe of legal token values for this bullet."""
    out: set[str] = set()
    fields = list(bullet.cites_fields or [])
    sg_ids = list(bullet.cites_sg_ids or [])
    if bullet.cites_sg_id and bullet.cites_sg_id not in sg_ids:
        sg_ids.append(bullet.cites_sg_id)

    by_id = {v.sg_id: v for v in bundle.variants}
    for sgid in sg_ids:
        v = by_id.get(sgid)
        if not v:
            continue
        out |= _collect_for_variant(v, fields or list(v.provenance.keys()))

    if bullet.slot == "volume_note":
        out |= _collect_volume_bound(bundle, actionable_count, skipped_by_class)

    return out


# ---- Token / value matching --------------------------------------------------


def _matches_any(token: str, bound_values: set[str]) -> bool:
    """A token verifies if its (case-insensitive) string appears in any
    bound value, OR if the bound value appears in the token (handles the
    'Conflicting' vs 'Conflicting_classifications_of_pathogenicity' case)."""
    if not token:
        return True
    t_norm = token.lower().replace("_", " ").replace(",", "")
    if token.startswith("ABCD_"):
        # Synthetic ABCD letter — match against any single-letter ABCD label.
        letter = token[-1]
        return any(str(v).strip() == letter for v in bound_values)
    for bv in bound_values:
        bv_norm = str(bv).lower().replace("_", " ").replace(",", "")
        if t_norm in bv_norm or bv_norm in t_norm:
            return True
    return False


# ---- Top-level verifier ------------------------------------------------------


def verify_bullet(
    bullet: BulletSlot,
    bundle: CaseBundle,
    skipped_by_class: dict[str, int],
    actionable_count: int,
) -> VerificationResult:
    if bullet.auto_generated:
        return VerificationResult(slot=bullet.slot, verified=True, total_tokens=0)
    tokens = extract_value_tokens(bullet.text)
    bound = collect_bound_values(bullet, bundle, skipped_by_class, actionable_count)
    unverified = [t for t in tokens if not _matches_any(t, bound)]
    return VerificationResult(
        slot=bullet.slot,
        verified=len(unverified) == 0,
        total_tokens=len(tokens),
        unverified_tokens=unverified,
    )


def verify_summary(summary: CaseSummary, bundle: CaseBundle) -> list[VerificationResult]:
    """Verify every bullet in the summary. The volume_note's bound aggregates
    are recomputed from the bundle so we don't depend on stored state."""
    from .ranker import rank_findings  # local import to avoid cycles

    ranked = rank_findings(bundle)
    actionable_count = len(ranked.actionable)
    skipped = ranked.skipped_summary
    return [
        verify_bullet(b, bundle, skipped, actionable_count) for b in summary.bullets
    ]
