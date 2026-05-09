"""
CaseBundle: the structured, provenance-tagged JSON that downstream code
(report drafter, verifier, renderer) treats as the source of truth for one
patient case.

Design rule: every clinically meaningful field on `VariantEvidence` carries a
`provenance` entry that names the VQS column it was sourced from. The verifier
later checks that any LLM-generated prose only references values that appear
in the bundle. If a field has no provenance, it cannot legitimately appear in
the report.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SampleHeader(_Frozen):
    """Patient/sample/run identity. Mostly comes from GraphQL findSamplesByIds."""

    sample_id: int
    sample_user_ref: str
    run_id: int
    run_user_ref: str
    pipeline_id: int
    pipeline_name: str
    panel_label: str
    reference_genome: str
    experiment_type: str  # e.g. "germline" / "somatic"
    insert_date: Optional[str] = None
    update_date: Optional[str] = None
    pmi_id: Optional[int] = None


class QCIndicator(_Frozen):
    name: str
    description: str
    value: Optional[float]
    range_lower: Optional[float]
    range_upper: Optional[float]
    status: str  # "PASSED" / "FAILED" / etc.
    category: Optional[str] = None


class VariantEvidence(_Frozen):
    """One row in the variant table, projected and provenance-tagged."""

    sg_id: str
    common_sg_id: Optional[str] = None

    gene_symbol: Optional[str] = None
    gene_code: Optional[int] = None

    transcript_name: Optional[str] = None
    transcript_version: Optional[str] = None
    in_mane: Optional[bool] = None

    chromosome: Optional[str] = None
    variant_type: Optional[str] = None  # SNV / INDEL
    consequence: Optional[str] = None  # e.g. "missense" / "synonymous" / "intronic"

    hgvs_c: Optional[str] = None
    hgvs_p: Optional[str] = None
    in_exon: Optional[int] = None
    position_in_exon: Optional[int] = None

    vaf_pct: Optional[float] = None
    read_depth: Optional[int] = None

    gnomad_genomes_af: Optional[float] = None
    gnomad_exomes_af: Optional[float] = None

    clinvar_significance: Optional[str] = None
    clinvar_review_status: Optional[str] = None

    abcd_label: Optional[str] = None  # in-house pathogenicity predictor (A/B/C/D)
    acmg_classification: Optional[str] = None  # Benign / Likely_benign / VUS / LP / P
    acmg_score: Optional[float] = None

    in_report: bool = False  # currently flagged for the clinical report
    is_false_positive: bool = False
    user_pathogenicity: Optional[str] = None

    # Maps each field name above -> source VQS column path. Provenance is
    # mandatory; see docstring.
    provenance: dict[str, str] = Field(default_factory=dict)


class CaseBundle(_Frozen):
    interpretation_id: str
    interpretation_name: str
    interpretation_status: str
    interpretation_etag: int
    analysis_id: int
    transcript_strategy_version: str

    sample: SampleHeader
    qc_indicators: list[QCIndicator] = Field(default_factory=list)
    variants: list[VariantEvidence] = Field(default_factory=list)

    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    # ----- Convenience aggregates (derived; not part of provenance contract) -----

    @property
    def variant_count(self) -> int:
        return len(self.variants)

    @property
    def acmg_breakdown(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for v in self.variants:
            k = v.acmg_classification or "unset"
            out[k] = out.get(k, 0) + 1
        return out

    @property
    def vus_or_pathogenic(self) -> list[VariantEvidence]:
        keep = {"VUS", "Likely_pathogenic", "Pathogenic"}
        return [v for v in self.variants if v.acmg_classification in keep]


# Mapping from VariantEvidence field -> source VQS column path. Used by the
# bundle assembler to populate `VariantEvidence.provenance` and by the
# verifier as the canonical "where could this fact have come from" map.
VARIANT_PROVENANCE: dict[str, str] = {
    "sg_id": "dynamic.sgId",
    "common_sg_id": "commonVariant.commonSgId",
    "gene_symbol": "transcriptome.gene.symbol",
    "gene_code": "transcriptome.gene.code",
    "transcript_name": "transcriptome.transcript.name",
    "transcript_version": "transcriptome.transcript.version",
    "in_mane": "transcriptome.transcriptInPanel.labels.MANE",
    "chromosome": "short.called.variant.location.chromosome.fullSeqName",
    "variant_type": "short.called.variant.type",
    "consequence": "short.annotated.transcriptContext.proteinVariant.consequence.sophiaName",
    "hgvs_c": "short.annotated.transcriptContext.transcriptVariant.cnomen.base",
    "hgvs_p": "short.annotated.transcriptContext.proteinVariant.pnomen.hgvsRefSeq",
    "in_exon": "short.annotated.transcriptContext.transcriptVariant.InExon",
    "position_in_exon": "short.annotated.transcriptContext.transcriptVariant.positionInExon",
    "vaf_pct": "short.called.alleleFrequency",
    "read_depth": "short.called.readDepth",
    "gnomad_genomes_af": "short.annotated.catalogs.gnomadGenomes.global.global.value",
    "gnomad_exomes_af": "short.annotated.catalogs.gnomadExomes.global.global.value",
    "clinvar_significance": "short.annotated.catalogs.clinvar.CLNSIG",
    "clinvar_review_status": "short.annotated.catalogs.clinvar.CLNREVSTAT",
    "abcd_label": "short_predictor.inhouse.predictors.ABCD.result.label",
    "acmg_classification": "userAnnotations.interpretation.acmg.result.classificationFinal",
    "acmg_score": "userAnnotations.interpretation.acmg.result.scoreFinal",
    "in_report": "userAnnotations.interpretation.inReport.flagged",
    "is_false_positive": "userAnnotations.analysis.falsePositive.flagged",
    "user_pathogenicity": "userAnnotations.account.pathogenicity.level",
}
