"""
Compose a CaseBundle for a given interpretation_id by combining:
  - interpretation metadata (REST search)
  - sample + QC (GraphQL findSamplesByIds)
  - pipeline / panel info (GraphQL findSgapipByIds)
  - variant rows from VQS LAYER2_SHORT_SUBSET
"""

from __future__ import annotations

from typing import Optional

from .case_bundle import (
    CaseBundle,
    QCIndicator,
    SampleHeader,
    VARIANT_PROVENANCE,
    VariantEvidence,
)
from .vqs_client import HCS_V2_PANEL_FILTER, VQSClient


def _row_to_variant(cols: list[str], row: list) -> VariantEvidence:
    """Map a single VQS variant row to a typed VariantEvidence."""

    def get(col: str):
        try:
            return row[cols.index(col)]
        except ValueError:
            return None

    def to_int(v):
        if v in (None, ""):
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    def to_float(v):
        if v in (None, ""):
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def to_bool(v) -> bool:
        return v in (True, "true", "TRUE", 1, "1")

    sg_id = get("dynamic.sgId")

    return VariantEvidence(
        sg_id=str(sg_id) if sg_id is not None else "",
        common_sg_id=(get("commonVariant.commonSgId") or None),
        gene_symbol=(get("transcriptome.gene.symbol") or None),
        gene_code=to_int(get("transcriptome.gene.code")),
        transcript_name=(get("transcriptome.transcript.name") or None),
        transcript_version=(get("transcriptome.transcript.version") or None),
        in_mane=to_bool(get("transcriptome.transcriptInPanel.labels.MANE")),
        chromosome=(get("short.called.variant.location.chromosome.fullSeqName") or None),
        variant_type=(get("short.called.variant.type") or None),
        consequence=(get("short.annotated.transcriptContext.proteinVariant.consequence.sophiaName") or None),
        hgvs_c=(get("short.annotated.transcriptContext.transcriptVariant.cnomen.base") or None),
        hgvs_p=(get("short.annotated.transcriptContext.proteinVariant.pnomen.hgvsRefSeq") or None),
        in_exon=to_int(get("short.annotated.transcriptContext.transcriptVariant.InExon")),
        position_in_exon=to_int(get("short.annotated.transcriptContext.transcriptVariant.positionInExon")),
        vaf_pct=to_float(get("short.called.alleleFrequency")),
        read_depth=to_int(get("short.called.readDepth")),
        gnomad_genomes_af=to_float(get("short.annotated.catalogs.gnomadGenomes.global.global.value")),
        gnomad_exomes_af=to_float(get("short.annotated.catalogs.gnomadExomes.global.global.value")),
        clinvar_significance=(get("short.annotated.catalogs.clinvar.CLNSIG") or None),
        clinvar_review_status=(get("short.annotated.catalogs.clinvar.CLNREVSTAT") or None),
        abcd_label=(get("short_predictor.inhouse.predictors.ABCD.result.label") or None),
        acmg_classification=(get("userAnnotations.interpretation.acmg.result.classificationFinal") or None),
        acmg_score=to_float(get("userAnnotations.interpretation.acmg.result.scoreFinal")),
        in_report=to_bool(get("userAnnotations.interpretation.inReport.flagged")),
        is_false_positive=to_bool(get("userAnnotations.analysis.falsePositive.flagged")),
        user_pathogenicity=(get("userAnnotations.account.pathogenicity.level") or None),
        provenance=dict(VARIANT_PROVENANCE),
    )


def _qc_from_sample(sample_record: dict) -> list[QCIndicator]:
    out: list[QCIndicator] = []
    for qi in sample_record.get("qualityIndicators", []) or []:
        out.append(QCIndicator(
            name=qi.get("name", ""),
            description=qi.get("description", "") or "",
            value=qi.get("value"),
            range_lower=qi.get("rangeLowerBound"),
            range_upper=qi.get("rangeUpperBound"),
            status=qi.get("status", "UNKNOWN"),
            category=qi.get("category"),
        ))
    return out


def _experiment_type_from_id(experiment_type_id: int) -> str:
    # 126000 is "germline" per findSgapipByIds; expand the table as needed.
    return {126000: "germline", 611407000: "somatic"}.get(
        experiment_type_id, f"unknown({experiment_type_id})"
    )


def build_sample_bundle(
    client: VQSClient,
    sample_id: int,
    *,
    panel_filter_fql: str = HCS_V2_PANEL_FILTER,
    panel_label_override: Optional[str] = None,
    reference_genome: str = "hg38",
) -> CaseBundle:
    """Sample-level bundle: ensures an interpretation exists for the sample
    (creates one auto-named if none), then assembles the same CaseBundle
    shape as build_case_bundle.

    Why we create an interpretation: VQS LAYER2_SHORT_SUBSET requires an
    `interpretation` key. Sample-level data without that context isn't
    materialized server-side. Creating a DRAFT interpretation gives us the
    server-side views we need, with no other side effects (no pipeline
    triggers, no reports submitted).
    """
    samples = client.find_samples_by_ids([sample_id])
    if not samples:
        raise LookupError(f"sample {sample_id} not found")
    sample = samples[0]

    interp = client.find_or_create_interpretation_for_sample(
        sample_id=int(sample["id"]),
        sample_user_ref=sample.get("userRef") or "",
        run_id=int(sample["ngsRunId"]),
    )
    return build_case_bundle(
        client,
        interp["id"],
        panel_filter_fql=panel_filter_fql,
        panel_label_override=panel_label_override,
        reference_genome=reference_genome,
    )


def build_case_bundle(
    client: VQSClient,
    interpretation_id: str,
    *,
    panel_filter_fql: str = HCS_V2_PANEL_FILTER,
    panel_label_override: Optional[str] = None,
    reference_genome: str = "hg38",
) -> CaseBundle:
    """Pull all the pieces and assemble a CaseBundle. Requires an authenticated client."""

    # 1. Find the interpretation.
    interps = client.search_interpretations(limit=200)
    interp = next((i for i in interps if i["id"] == interpretation_id), None)
    if interp is None:
        raise LookupError(f"interpretation {interpretation_id!r} not visible to this account")

    analysis_id = int(interp["analysisId"])
    etag = int(interp["etag"])
    tsv = str(interp["createdAt"])

    # 2. Sample + QC. The sample id matches the analysis id in this dataset's
    #    convention; if that ever drifts we resolve it via findAnalysisResults.
    samples = client.find_samples_by_ids([analysis_id])
    if not samples:
        raise LookupError(f"no sample record for analysis {analysis_id}")
    sample = samples[0]

    # 3. Pipeline / panel name.
    panel_label = panel_label_override or ""
    if not panel_label:
        try:
            pipes = client.find_pipelines_by_ids([sample["sgaPipId"]])
            if pipes:
                panel_label = pipes[0].get("dgName") or ""
        except Exception:
            panel_label = ""

    header = SampleHeader(
        sample_id=int(sample["id"]),
        sample_user_ref=sample.get("userRef") or "",
        run_id=int(sample["ngsRunId"]),
        run_user_ref=(sample.get("ngsRun") or {}).get("userRef") or "",
        pipeline_id=int(sample["sgaPipId"]),
        pipeline_name=panel_label or f"sgapip-{sample['sgaPipId']}",
        panel_label=panel_label or "Hereditary Cancer (panel name unresolved)",
        reference_genome=reference_genome,
        experiment_type=_experiment_type_from_id(int(sample["experimentTypeId"])),
        insert_date=sample.get("insertDate"),
        update_date=sample.get("updateDate"),
        pmi_id=int(sample.get("sgaPmiId") or 0) or None,
    )
    qc = _qc_from_sample(sample)

    # 4. Variants. The first call may 500 if the interpretation's server-side
    #    phenotype-ranking views haven't been materialized (they're created
    #    lazily when a user opens the case in Gen2). Auto-warm and retry once.
    def _fetch():
        return client.get_short_subset_variants(
            analysis_id=analysis_id,
            interpretation_id=interpretation_id,
            transcript_strategy_version=tsv,
            gene_filter_fql=panel_filter_fql,
            pmi_id=header.pmi_id or 0,
            interpretation_etag=etag,
        )

    try:
        cols, rows = _fetch()
    except RuntimeError as e:
        msg = str(e)
        if "VQS 500" in msg or "Internal Server Error" in msg:
            print(f"   warming {interpretation_id} (server-side views not ready)...")
            from .warmup import warmup_interpretation
            warmup_interpretation(interpretation_id)
            cols, rows = _fetch()
        else:
            raise
    variants = [_row_to_variant(cols, row) for row in rows]

    return CaseBundle(
        interpretation_id=interpretation_id,
        interpretation_name=interp.get("name", ""),
        interpretation_status=interp.get("status", ""),
        interpretation_etag=etag,
        analysis_id=analysis_id,
        transcript_strategy_version=tsv,
        sample=header,
        qc_indicators=qc,
        variants=variants,
    )
