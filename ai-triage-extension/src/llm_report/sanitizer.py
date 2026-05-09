"""
Deterministic post-processor for CaseSummary instances.

The UI shows structured information (priority badge, QC badge, panel label,
experiment type, sample id, etc.) outside the AI card. The AI prose should
not duplicate any of that. The LLM is asked to skip it via prompt, but it
sometimes leaks redundant trailing phrases (", QC clean.", ", QC pass.")
or restates the panel name. This module strips those mechanically so the
behavior is reliable regardless of the LLM run.

Single source of truth: REDUNDANT_PATTERNS lists facts already on screen.
Add to it as the surrounding UI gains new structured fields.
"""

from __future__ import annotations

import re

from .case_summary import CaseSummary


# Whole-bullet patterns: if a bullet is *only* this kind of redundant
# statement, drop the bullet entirely.
REDUNDANT_BULLET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^all qc (?:indicators? )?(?:passed|pass)\b.*", re.IGNORECASE),
    re.compile(r"^qc (?:passed|pass|clean)\b.*", re.IGNORECASE),
    re.compile(r"^germline (?:experiment|sequencing|testing|sample)\b.*", re.IGNORECASE),
    re.compile(r"^somatic (?:experiment|sequencing|testing|sample)\b.*", re.IGNORECASE),
    re.compile(r".*sophia\s*ddm\s+hereditary\s+cancer\s+solution.*", re.IGNORECASE),
    re.compile(r"^panel:\s+", re.IGNORECASE),
]


# Suffix phrases to peel off the END of a headline or bullet. Order matters:
# longer first so we don't leave a fragment.
TRAILING_SUFFIXES: list[str] = [
    ". All QC indicators PASSED.",
    ". All QC indicators PASSED",
    "; All QC indicators PASSED.",
    ", All QC indicators PASSED.",
    ", QC clean.",
    ", QC clean",
    ", QC pass.",
    ", QC pass",
    ", QC PASS.",
    ", QC PASS",
    ", QC passed.",
    ", QC passed",
    ", QC PASSED.",
    ", QC PASSED",
    ". QC clean.",
    ". QC pass.",
    ". QC PASS.",
    ". QC passed.",
    ". QC PASSED.",
]


def _strip_trailing(text: str) -> str:
    if not text:
        return text
    s = text.strip()
    while True:
        changed = False
        for suf in TRAILING_SUFFIXES:
            if s.lower().endswith(suf.lower()):
                s = s[: -len(suf)].rstrip(" ,;:.")
                changed = True
                break
        if not changed:
            break
    # Restore single trailing period.
    if s and s[-1] not in ".!?":
        s = s + "."
    return s


def _is_redundant_bullet(bullet: str) -> bool:
    if not bullet or not bullet.strip():
        return True
    return any(p.search(bullet) for p in REDUNDANT_BULLET_PATTERNS)


def clean_summary(summary: CaseSummary) -> CaseSummary:
    """Return a CaseSummary with redundant prose stripped out.

    Operates on each ``BulletSlot.text``. Templated slots (auto_generated=True)
    are skipped — they're already deterministic. Idempotent.
    """
    cleaned_headline = _strip_trailing(summary.headline)
    cleaned_bullets = []
    for b in summary.bullets:
        if b.auto_generated:
            cleaned_bullets.append(b)
            continue
        if _is_redundant_bullet(b.text):
            # Don't drop the slot — keep its citations + replace the text
            # with a stripped version. If the entire bullet is redundant we
            # at least preserve provenance for the verifier.
            stripped = _strip_trailing(b.text)
            cleaned_bullets.append(b.model_copy(update={"text": stripped}))
            continue
        cleaned_bullets.append(b.model_copy(update={"text": _strip_trailing(b.text)}))
    return summary.model_copy(update={
        "headline": cleaned_headline,
        "bullets": cleaned_bullets,
    })
