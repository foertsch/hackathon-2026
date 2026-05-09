"""
Thin client for SOPHiA DDM Gen2's variant + metadata APIs.

Three layers:
  1. Low-level VQS POST (single + multi-slot Query bodies).
  2. GraphQL helpers for the metadata we need to compose the right keys.
  3. A high-level helper that pulls the variant table for an interpretation,
     paginating until done.

The dataset key the SPA sends is base64(JSON) of:
  { "ficId": <file id>, "knownFile": <enum>, "analysisId": <long>,
    "interpretation": <interp-id>, "transcriptStrategyVersion": <millis> }

For some `knownFile` values (SHORT_GENE_VIEW / CNV_GENE_VIEW) the server resolves
the file id, so ficId=-1 is acceptable. For LAYER2_* keys the ficId is required;
we look it up via the `findAnalysisResults` GraphQL op.
"""

from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

import requests

PLATFORM = "https://platform-vandv1.sophiagenetics.com"
VQS_URL = f"{PLATFORM}/api/variant/query"
VQS_MULTI_URL = f"{VQS_URL}/multi"
VQS_SCHEMA_URL = f"{VQS_URL}/schema"
GENOMIC_GRAPHQL = f"{PLATFORM}/api/genomic/data/graphql"
INTERP_SEARCH = f"{PLATFORM}/api/interpretation/v1/search"

# knownFile -> filename suffix observed in findAnalysisResults output. Used to
# look up the ficId for a (analysisId, knownFile) pair.
KNOWN_FILE_TO_FILENAME = {
    "LAYER2_SHORT_DATASET": "DNA_VARIANT_SHORT_layer2_dataset.json",
    "LAYER2_SHORT_SUBSET_DATASET_PLUS_GENE_ANNOTATIONS": "DNA_VARIANT_SHORT_layer2_dataset.json",
    "LAYER2_CNV_DATASET_PLUS_GENE_ANNOTATIONS": "DNA_VARIANT_CNV_layer2_dataset.json",
    "LAYER2_GENE_ANNOTATION_DATASET": "GENE_ANNOTATION_DATA_layer2_dataset.json",
    "LAYER1_ANALYSIS_DATASET": "layer1.dataset.json",
    "GENE_LAYER_1": "gene_annotations.parquet",
    "EXON_COVERAGE_STATS": "exon_coverage_stats_v3.txt",
    "TER_ANALYSIS_OUTPUT_CNV_CATALOG_DBVAR": "cnv_catalog_dbvar.parquet",
}

# Server-resolved (no ficId needed):
SERVER_RESOLVED = {"SHORT_GENE_VIEW", "CNV_GENE_VIEW"}

# Gene-panel filter for SOPHiA DDM Hereditary Cancer Solution v2. Captured
# verbatim from the live SPA. The 83 gene codes are the panel's gene set.
HCS_V2_PANEL_FILTER = (
    "fql:(((transcriptome.gene.code anyOf "
    "(37370,23527,8298,5585,7006,32283,24498,28413,1183,23129,31155,15907,"
    "8208,38546,5579,37414,6701,28094,1779,21512,39462,9156,19155,13892,"
    "36793,30171,31024,29230,2235,30099,35387,31869,13735,34856,38283,16374,"
    "18478,15085,9244,20991,38520,24750,19482,30442,16939,26450,24194,10758,"
    "29842,35212,34563,32582,1310,656,37237,6646,4306,32546,17273,4760,40111,"
    "38872,20483,4123,18244,9336,3750,20769,33181,40998,27835,7151,14926,2338,"
    "38918,621,105,7701,4114,37226,39800,37942,36812,18889) "
    "AND transcriptome.transcriptInPanel.geneInPanel = true) "
    "OR (short.annotated.transcriptContext.proteinVariant.consequence.sophiaName = 'intergenic' "
    "AND transcriptome.gene.symbol is empty)) "
    "AND (short.called.filter.bool.PASS = true "
    "AND short.called.variant.type anyOf ('INDEL','SNV')))"
)


def _b64_key(d: dict) -> str:
    return base64.b64encode(
        json.dumps(d, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")


@dataclass
class DatasetKey:
    known_file: str
    analysis_id: Optional[int] = None
    fic_id: Optional[int] = None
    interpretation: Optional[str] = None
    transcript_strategy_version: Optional[str] = None
    target_entities: Optional[str] = None

    def encode(self) -> str:
        d: dict[str, Any] = {}
        if self.fic_id is not None:
            d["ficId"] = self.fic_id
        elif self.known_file in SERVER_RESOLVED:
            d["ficId"] = -1
        d["knownFile"] = self.known_file
        if self.analysis_id is not None:
            d["analysisId"] = self.analysis_id
        if self.interpretation is not None:
            d["interpretation"] = self.interpretation
        if self.transcript_strategy_version is not None:
            d["transcriptStrategyVersion"] = self.transcript_strategy_version
        if self.target_entities is not None:
            d["targetEntities"] = self.target_entities
        return _b64_key(d)


class VQSClient:
    """All HTTP traffic against Gen2 funnels through here."""

    def __init__(self, session: requests.Session):
        self.s = session

    # ---------- VQS ----------

    def schema(
        self,
        key: DatasetKey,
        transformers: Iterable[str] = ("FLATTEN",),
        plan_params: Optional[dict] = None,
    ) -> list[str]:
        params = self._common_params(key, transformers, plan_params)
        r = self.s.get(VQS_SCHEMA_URL, params=params, timeout=30)
        r.raise_for_status()
        return r.json().get("columns", [])

    def query(
        self,
        key: DatasetKey,
        body: dict,
        transformers: Iterable[str] = ("FLATTEN",),
        plan_params: Optional[dict] = None,
        timeout: float = 60,
    ) -> dict:
        params = self._common_params(key, transformers, plan_params)
        r = self.s.post(VQS_URL, params=params, json=body, timeout=timeout)
        r.raise_for_status()
        return r.json()

    def query_rows(self, *args, **kwargs) -> tuple[list[str], list[list]]:
        """Return (columns, data) for a single-page query."""
        resp = self.query(*args, **kwargs)
        # Multi-slot responses wrap pageContent under a slot name.
        if "pageContent" in resp:
            pc = resp["pageContent"]
            return pc.get("columns", []), pc.get("data", [])
        if "retained" in resp:
            pc = resp["retained"].get("pageContent", {})
            return pc.get("columns", []), pc.get("data", [])
        raise RuntimeError(f"Unexpected VQS response shape: keys={list(resp)}")

    def query_paged(
        self,
        key: DatasetKey,
        body: dict,
        transformers: Iterable[str],
        plan_params: Optional[dict],
        *,
        page_size: int = 100,
    ) -> tuple[list[str], list[list]]:
        """Iterate over pages until the server stops returning rows."""
        all_rows: list[list] = []
        cols: list[str] = []
        offset = 0
        while True:
            paged_body = json.loads(json.dumps(body))  # deep-copy
            paged_body["pagination"] = {"offset": offset, "limit": page_size}
            c, rows = self.query_rows(key, paged_body, transformers, plan_params)
            if not cols:
                cols = c
            if not rows:
                break
            all_rows.extend(rows)
            if len(rows) < page_size:
                break
            offset += len(rows)
        return cols, all_rows

    @staticmethod
    def _common_params(
        key: DatasetKey, transformers: Iterable[str], plan_params: Optional[dict]
    ) -> dict:
        params: dict[str, Any] = {
            "key": key.encode(),
            "plan.transformers": ",".join(transformers),
        }
        for k, v in (plan_params or {}).items():
            params[f"plan.parameters.{k}"] = v
        return params

    # ---------- Metadata: REST ----------

    def get_interpretation(self, interpretation_id: str) -> dict:
        r = self.s.get(
            f"{INTERP_SEARCH}/{interpretation_id}", timeout=15,
        )
        r.raise_for_status()
        return r.json()

    def create_interpretation(
        self,
        *,
        name: str,
        analysis_id: int,
        run_id: int,
        virtual_panel_id: str = "root:5749",
        root_panel_id: str = "root:5749",
        type_: str = "DEFAULT",
    ) -> dict:
        """POST /api/interpretation/v1/create. Returns the new interpretation."""
        body = {
            "name": name,
            "analysis": [str(analysis_id)],
            "virtualPanelId": virtual_panel_id,
            "rootPanelId": root_panel_id,
            "phenotypeIds": None,
            "batchAnalysisId": str(run_id),
            "type": type_,
        }
        r = self.s.post(
            f"{PLATFORM}/api/interpretation/v1/create", json=body, timeout=30,
        )
        if r.status_code not in (200, 201):
            raise RuntimeError(f"create_interpretation {r.status_code}: {r.text[:300]}")
        return r.json()

    def find_or_create_interpretation_for_sample(
        self, sample_id: int, sample_user_ref: str, run_id: int
    ) -> dict:
        """Return the most recent interpretation for the sample, creating one
        if none exists."""
        existing = [
            i for i in self.search_interpretations(limit=200)
            if int(i.get("analysisId", 0)) == int(sample_id)
        ]
        if existing:
            existing.sort(key=lambda i: int(i.get("createdAt", 0)), reverse=True)
            return existing[0]
        # Create one. Name format mirrors what Gen2's UI auto-fills.
        from datetime import datetime, timezone
        date_str = datetime.now(timezone.utc).strftime("%Y %b %d")
        name = f"{sample_user_ref} - {date_str} - Interpretation (auto)"
        return self.create_interpretation(
            name=name, analysis_id=sample_id, run_id=run_id,
        )

    def search_interpretations(
        self, query: str = "", limit: int = 50, page: int = 0
    ) -> list[dict]:
        body = {
            "page": page, "limit": limit, "query": query, "status": "",
            "analysisIds": [], "interpretationIds": [], "createDateFilter": {},
            "editDateFilter": {}, "orderBy": "created_at", "ascending": False,
        }
        r = self.s.post(INTERP_SEARCH, json=body, timeout=30)
        r.raise_for_status()
        return r.json().get("interpretations", [])

    # ---------- Metadata: GraphQL ----------

    def graphql(self, query: str, variables: dict, url: str = GENOMIC_GRAPHQL) -> dict:
        r = self.s.post(url, json={"query": query, "variables": variables}, timeout=30)
        if r.status_code == 401:
            # Bearer expired; refresh once then retry.
            self._refresh_bearer()
            r = self.s.post(url, json={"query": query, "variables": variables}, timeout=30)
        r.raise_for_status()
        body = r.json()
        if "errors" in body and body["errors"]:
            raise RuntimeError(f"GraphQL errors: {body['errors']}")
        return body.get("data", {})

    def _refresh_bearer(self) -> None:
        """Re-fetch the bearer token from /web/gateway/api/auth/session.
        Cookies are still valid; only the JWT has expired."""
        try:
            r = self.s.get(f"{PLATFORM}/web/gateway/api/auth/session", timeout=15)
            if r.status_code == 200:
                tok = r.json().get("iam_access_token")
                if tok:
                    self.s.headers["Authorization"] = f"Bearer {tok}"
                    return
        except Exception:
            pass
        # Cookies are also stale: full re-login via Playwright.
        from .auth import get_session
        new_s = get_session(force_refresh=True)
        self.s.cookies.clear()
        for k, v in new_s.cookies.items():
            self.s.cookies.set(k, v)
        if "Authorization" in new_s.headers:
            self.s.headers["Authorization"] = new_s.headers["Authorization"]

    def find_analysis_results(self, analysis_id: int) -> dict:
        q = """
        query findAnalysisResults($analysisId: Long!) {
          findAnalysisResults(analysisId: $analysisId) {
            id
            analysisId
            files {
              id filename status ioType activeStorageUrl
            }
          }
        }"""
        data = self.graphql(q, {"analysisId": analysis_id})
        return data.get("findAnalysisResults") or {}

    def fic_id_for(self, analysis_id: int, known_file: str) -> int:
        """Resolve (analysisId, knownFile) -> ficId via findAnalysisResults."""
        if known_file in SERVER_RESOLVED:
            return -1
        suffix = KNOWN_FILE_TO_FILENAME.get(known_file)
        if not suffix:
            raise KeyError(f"No filename mapping for knownFile={known_file}")
        result = self.find_analysis_results(analysis_id)
        for f in result.get("files", []) or []:
            if f.get("filename", "").endswith(suffix) and f.get("status") == "ACTIVE":
                return int(f["id"])
        raise LookupError(
            f"No ACTIVE file matching {suffix!r} for analysis {analysis_id}"
        )

    def find_samples_by_ids(self, ids: list[int]) -> list[dict]:
        q = """
        query findSamplesByIds($ids: [Long]!) {
          findSamplesByIds(ids: $ids) {
            id userRef experimentTypeId analysisTypeId kitId
            ngsRunId ngsRun { id userRef }
            insertDate updateDate sgaPipId sgpPpiId sgaPmiId status
            qualityIndicators {
              id sampleId name description category specificity
              status rangeLowerBound rangeUpperBound value
            }
            platformVersion
          }
        }"""
        return self.graphql(q, {"ids": ids}).get("findSamplesByIds", []) or []

    # ---------- High-level: pull variant table for an interpretation ----------

    # Columns the Variants tab projects (41 cols). Captured from interp-1047.
    VARIANT_TAB_COLUMNS: list[str] = [
        "dynamic.sgId",
        "commonVariant.commonSgId",
        "transcriptome.gene.code",
        "transcriptome.gene.symbol",
        "short.annotated.transcriptSelect.mappedGenesInPanel",
        "transcriptome.transcript.name",
        "transcriptome.transcript.version",
        "transcriptome.transcript.database",
        "short.annotated.transcriptSelect.byFVT",
        "transcriptome.transcriptInPanel.labels.MANE",
        "transcriptome.transcriptInPanel.labels.MANE_PLUS",
        "transcriptome.transcript.cdsLongest",
        "short.called.variant.location.chromosome.fullSeqName",
        "short_predictor.inhouse.predictors.ABCD.result.label",
        "short.annotated.transcriptContext.transcriptVariant.cnomen.base",
        "short.annotated.transcriptContext.proteinVariant.pnomen.hgvsRefSeq",
        "short.called.alleleFrequency",
        "short.called.readDepth",
        "short.annotated.transcriptContext.transcriptVariant.InExon",
        "short.annotated.transcriptContext.transcriptVariant.positionInExon",
        "short.called.variant.type",
        "short.annotated.transcriptContext.proteinVariant.consequence.sophiaNameSelect",
        "short.annotated.transcriptContext.proteinVariant.consequence.sophiaName",
        "short.annotated.transcriptContext.proteinVariant.consequence.trueIntergenic",
        "short.annotated.catalogs.gnomadGenomes.global.global.value",
        "short.annotated.catalogs.gnomadExomes.global.global.value",
        "userAnnotations.interpretation.acmg.result.classificationFinal",
        "userAnnotations.interpretation.acmg.result.score",
        "userAnnotations.interpretation.acmg.result.scoreFinal",
        "short.annotated.catalogs.clinvar.CLNREVSTAT",
        "short.annotated.catalogs.clinvar.CLNSIG",
        "userAnnotations.account.pathogenicity.level",
        "userAnnotations.analysis.falsePositive.id",
        "userAnnotations.account.falsePositive.flagged",
        "userAnnotations.analysis.falsePositive.etag",
        "userAnnotations.interpretation.inReport.flagged",
        "userAnnotations.analysis.falsePositive.flagged",
        "userAnnotations.account.inReport.flagged",
        "userAnnotations.account.variantDescription.flagged",
    ]

    @staticmethod
    def _quote_col(c: str) -> str:
        # FQL/DuckDB requires column names with dots to be double-quoted.
        return f'"{c}"' if "." in c else c

    def get_short_full_variants(
        self,
        analysis_id: int,
        gene_filter_fql: str,
        *,
        page_size: int = 500,
    ) -> tuple[list[str], list[list]]:
        """Fetch the panel-filtered variant table for a sample without an
        interpretation context. Used for sample-level summaries (no user
        annotations overlay).

        Backed by LAYER2_SHORT_DATASET (the non-subset, non-interpretation
        variant). The columns we project are the variant-tab projection minus
        the userAnnotations.* fields (which only exist on interpretations).
        """
        fic = self.fic_id_for(analysis_id, "LAYER2_SHORT_DATASET")
        key = DatasetKey(
            known_file="LAYER2_SHORT_DATASET",
            fic_id=fic,
            analysis_id=analysis_id,
        )
        # Strip userAnnotations.* columns; not available without an interp.
        cols = [c for c in self.VARIANT_TAB_COLUMNS if not c.startswith("userAnnotations.")]
        column_sorts = [
            {"column": '"short_predictor.inhouse.predictors.ABCD.result.label"', "sort": "ASC"},
            {"column": '"dynamic.sgId"', "sort": "ASC"},
        ]
        all_rows: list[list] = []
        page_cols: list[str] = []
        offset = 0
        while True:
            body = {
                "columns": [self._quote_col(c) for c in cols],
                "columnSorts": column_sorts,
                "filters": {"filterString": gene_filter_fql},
                "groupBy": ["*"],
                "pagination": {"offset": offset, "limit": page_size},
            }
            params = self._common_params(key, ["FLATTEN"], None)
            params["engine.paginate"] = "true"
            params["engine.maxPaginationRows"] = "500"
            r = self.s.post(VQS_URL, params=params, json=body, timeout=120)
            if r.status_code != 200:
                raise RuntimeError(f"VQS {r.status_code}: {r.text[:500]}")
            resp = r.json()
            pc = resp.get("pageContent", {}) or {}
            rows = pc.get("data", []) or []
            if not page_cols:
                page_cols = pc.get("columns", []) or []
            if not rows:
                break
            all_rows.extend(rows)
            if len(rows) < page_size:
                break
            offset += len(rows)
        return page_cols, all_rows

    def get_short_subset_variants(
        self,
        analysis_id: int,
        interpretation_id: str,
        transcript_strategy_version: str,
        gene_filter_fql: str,
        *,
        pmi_id: int,
        interpretation_etag: int,
        page_size: int = 500,
    ) -> tuple[list[str], list[list]]:
        """Fetch all rows from LAYER2_SHORT_SUBSET (Variants tab data).

        Uses the multi-slot body shape (`shortTotalCount` + `retained`) that the
        SPA sends in production.
        """
        fic = self.fic_id_for(analysis_id, "LAYER2_SHORT_SUBSET_DATASET_PLUS_GENE_ANNOTATIONS")
        key = DatasetKey(
            known_file="LAYER2_SHORT_SUBSET_DATASET_PLUS_GENE_ANNOTATIONS",
            fic_id=fic,
            analysis_id=analysis_id,
            interpretation=interpretation_id,
            transcript_strategy_version=str(transcript_strategy_version),
        )
        # The count slot uses the panel filter without the PASS/type predicate.
        # The retained (data) slot uses the full filter with PASS+type. This is
        # what Gen2 sends — preserved verbatim.
        count_filter = gene_filter_fql.replace(
            " AND (short.called.filter.bool.PASS = true "
            "AND short.called.variant.type anyOf ('INDEL','SNV')))",
            ")",
        ).replace("fql:(((", "fql:((", 1)  # strip the extra wrapping paren

        column_sorts = [
            {"column": '"short_predictor.inhouse.predictors.ABCD.result.label"', "sort": "ASC"},
            {"column": '"dynamic.sgId"', "sort": "ASC"},
        ]

        all_rows: list[list] = []
        cols: list[str] = []
        offset = 0
        while True:
            # Single-Query body shape — the plain /api/variant/query endpoint
            # expects this, not the multi-slot wrapper. The multi-slot shape
            # belongs on /api/variant/query/multi.
            body = {
                "columns": [self._quote_col(c) for c in self.VARIANT_TAB_COLUMNS],
                "columnSorts": column_sorts,
                "filters": {"filterString": gene_filter_fql},
                "groupBy": ["*"],
                "pagination": {"offset": offset, "limit": page_size},
            }
            transformers = [
                "FLATTEN", "USER_ANNOTATIONS", "PHENOTYPIC_RANKING",
                "USER_ANNOTATIONS_REFRESH", "PHENOTYPIC_RANKING_REFRESH",
                "SHORT_SUBSET",
            ]
            plan_params = {
                "uaVariantId": "COMMON_SGID",
                "experimentTypeId": 126000,
                "pmiId": pmi_id,
                "analysisId": analysis_id,
                "interpretationId": interpretation_id,
                "uaAcmgOverrideVersion": 0,
                "uaAcmgCnvOverrideVersion": 0,
                "uaVariantInReportVersion": 0,
                "uaFalsePositiveVersion": 0,
                "uaVariantDescriptionVersion": 0,
                "uaPathogenicityVersion": 0,
                "interpretationEtag": interpretation_etag,
                "uaMrdMarkerVersion": 0,
            }
            engine = {"engine.paginate": "true", "engine.maxPaginationRows": "500"}
            params = self._common_params(key, transformers, plan_params)
            params.update(engine)
            # Retry transient 5xx (test instance is shared; brief 500 is common).
            r = None
            for vqs_attempt in range(3):
                r = self.s.post(VQS_URL, params=params, json=body, timeout=120)
                if r.status_code == 200:
                    break
                if r.status_code == 401 and vqs_attempt == 0:
                    self._refresh_bearer()
                    continue
                if r.status_code < 500 or vqs_attempt == 2:
                    raise RuntimeError(f"VQS {r.status_code}: {r.text[:500]}")
                time.sleep(0.8 * (vqs_attempt + 1))
            resp = r.json()
            if offset == 0 and os.environ.get("VQS_DEBUG"):
                Path("/tmp/vqs_resp.json").write_text(json.dumps(resp, indent=2)[:4000])
                Path("/tmp/vqs_req.json").write_text(json.dumps({"params": params, "body": body}, indent=2))
                print(f"   [debug] dumped /tmp/vqs_req.json /tmp/vqs_resp.json (resp keys: {list(resp)})")
            pc = resp.get("pageContent", {}) or resp.get("retained", {}).get("pageContent", {})
            page_cols = pc.get("columns", []) or []
            page_rows = pc.get("data", []) or []
            if not cols and page_cols:
                cols = page_cols
            if not page_rows:
                break
            all_rows.extend(page_rows)
            if len(page_rows) < page_size:
                break
            offset += len(page_rows)
        return cols, all_rows

    def find_pipelines_by_ids(self, ids: list[int]) -> list[dict]:
        q = """
        query findSgapipByIds($ids: [ID]!) {
          pipelines: findSgapipByIds(ids: $ids) {
            id dgName analysisTypeId kitId sampleTypeId
            experimentTypeFK { id fullName code }
            kitFK { code fullName id }
            sequencerFK { code id fullName }
            genePanel hasCNV hasFusion paired
          }
        }"""
        # Note: this op shape was observed in HAR; field set is conservative.
        return self.graphql(q, {"ids": ids}, url=f"{PLATFORM}/api/products/v1/graphql").get("pipelines", []) or []


if __name__ == "__main__":
    from .auth import get_session
    s = get_session()
    c = VQSClient(s)
    interps = c.search_interpretations()
    print(f"interpretations: {len(interps)}")
    for i in interps:
        print(f"  {i['id']:30s} analysisId={i['analysisId']:12s} {i['name']}")
    if interps:
        from collections import Counter
        target = next((i for i in interps if i["id"] == "interpretation-1047"), interps[0])
        analysis_id = int(target["analysisId"])
        samples = c.find_samples_by_ids([analysis_id])
        pmi_id = samples[0]["sgaPmiId"] if samples else 0
        cols, rows = c.get_short_subset_variants(
            analysis_id, target["id"], str(target["createdAt"]),
            HCS_V2_PANEL_FILTER,
            pmi_id=pmi_id, interpretation_etag=int(target["etag"]),
        )
        sym_idx = cols.index("transcriptome.gene.symbol")
        acmg_idx = cols.index("userAnnotations.interpretation.acmg.result.classificationFinal")
        abcd_idx = cols.index("short_predictor.inhouse.predictors.ABCD.result.label")
        print(f"\n{target['id']}: {len(cols)} cols x {len(rows)} rows")
        print(f"  genes: {Counter(r[sym_idx] for r in rows if r[sym_idx]).most_common(8)}")
        print(f"  ACMG: {dict(Counter(r[acmg_idx] or 'unset' for r in rows))}")
        print(f"  ABCD: {dict(Counter(r[abcd_idx] or 'unset' for r in rows))}")
