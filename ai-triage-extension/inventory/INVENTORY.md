# Gen2 / VQS Inventory — `hackathon1@hackathon.com`

Captured 2026-05-09 by walking the Gen2 SPA with Playwright.
Full HARs in `har/`, screenshots in `screenshots/`, raw dumps in `dumps/`.

## Auth model

- B2C OAuth at `https://b2cstagingsophia.b2clogin.com/...` redirects back to
  `/web/gateway/api/auth/callback/sophia`. After login the SPA uses
  **session cookies** (not a bearer token) for API calls.
- Direct call to `https://iam-vandv.sophiagenetics.com/account/token` returns
  401 — the IAM token endpoint described in the API doc is NOT auto-issued by
  the session cookie. To grab a usable bearer token, snipe it from a request
  in the browser's network tab (`Authorization: Bearer ...`) or call
  `iam-vandv` with a different auth flow we'd have to discover.
- Practical path for the build: drive the API the same way the SPA does —
  reuse Playwright's authenticated context (`page.request.post(...)`) which
  attaches cookies automatically. No manual bearer needed.

## Routing

- `/web/landing` — release-notes / company landing.
- `/web/genomics` — Genomics module home (My applications + My work).
- `/web/genomics/finder/<interpretation-id>` — the case interpretation view
  (Overview/Quality/Genes/Variants/Report tabs). **This is the URL pattern.**

## Data hierarchy in the test env

Two NGS runs are pre-loaded:

| Run | userRef | sgaPipId | Pipeline name | Sample count |
|---|---|---|---|---|
| 200003854 | `Hackathon - Hereditary Cancer Run` | 6287 | SOPHiA DDM Hereditary Cancer Solution v2 (germline, hg38, Multiplicom MASTR / NextSeq) | 2 (SG063-LPA, 17br088-1-Run1) |
| 200003896 | `Hackathon - Somatic run` | 8825 | (somatic; analyses run, no interpretations created yet) | ~30 |

Four pre-loaded interpretations, all on the Hereditary Cancer run, all `status:DRAFT`:

| Interpretation | Name | analysisId | Sample |
|---|---|---|---|
| `interpretation-1047` | SG063-LPA · 2026 May 08 · #3 | 200042365 | SG063-LPA |
| `interpretation-1046` | SG063-LPA · 2026 May 07 · #2 | 200042365 | SG063-LPA |
| `interpretation-1043` | SG063-LPA · 2026 May 07 | 200042365 | SG063-LPA |
| `interpretation-1042` | 17br088-1-Run1 · 2026 May 06 | 200042360 | 17br088-1-Run1 |

`interpretation-1042 / analysisId 200042360` is the case the official VQS API doc uses
in its example query — useful as a known-good reference while building.

## Sample QC available from GraphQL

`POST /api/genomic/data/graphql` with op `findSamplesByIds` returns a
`qualityIndicators[]` block per sample with real values, e.g. SG063-LPA:

| Indicator | Value | Range | Status |
|---|---|---|---|
| `cov_unif` (coverage uniformity) | 0.999 | 0.99–1.00 | PASSED |
| `panel_cov_percentile_200` (% target ≥200×) | 99.884 | 95–100 | PASSED |
| `onTarget_bases` | 0.857 | 0.7–1.0 | PASSED |

These plug directly into the report's QC section.

## VQS dataset taxonomy (from real Gen2 traffic)

The `key` query param is base64-JSON like
`{"ficId":206507563,"knownFile":"...","analysisId":200042365,"interpretation":"interpretation-1047","transcriptStrategyVersion":"1778250225000"}`.
`knownFile` enumerates the available datasets:

| `knownFile` | Purpose | Powers UI |
|---|---|---|
| `LAYER1_ANALYSIS_DATASET` | Raw analysis layer (pre-annotation). | (internal) |
| `LAYER2_SHORT_DATASET` | All short variants (SNV/INDEL), fully annotated — **994 columns**. | Variants tab (full mode) |
| `LAYER2_SHORT_SUBSET_DATASET_PLUS_GENE_ANNOTATIONS` | Same but scoped to the panel + joined with gene annotations. | Variants tab (default subset view) |
| `LAYER2_CNV_DATASET_PLUS_GENE_ANNOTATIONS` | CNV variants + gene annotations. | CNV tab |
| `LAYER2_GENE_ANNOTATION_DATASET` | Gene-level annotations. | Genes tab |
| `GENE_LAYER_1` | Gene layer (panel structure). | Genes tab |
| `EXON_COVERAGE_STATS` | Per-exon coverage. | Quality tab |
| `SHORT_GENE_VIEW` / `CNV_GENE_VIEW` | Per-gene aggregations of variants. | Genes tab |
| `ACCOUNT_VARIANT_TO_ANALYSIS_DATASET` | Cross-analysis user annotations. | Variants tab (community signal) |
| `TER_ANALYSIS_OUTPUT_CNV_CATALOG_DBVAR` | DBVAR reference. | CNV reference |

**Transformer chains observed:** `FLATTEN`, `USER_ANNOTATIONS(+_REFRESH)`,
`PHENOTYPIC_RANKING(+_REFRESH)`, `SHORT_SUBSET`, `GENE_VIEW_SHORT/CNV`.

## Variant column landscape (LAYER2_SHORT_DATASET — 994 cols)

Full list saved to `dumps/41_layer2_short_columns.txt`. Highlights, organised:

- **Identity**: `dynamic.sgId`, `dynamic.legacy.sgId`, `commonVariant.commonSgId`
- **Genomic location**: `short.called.variant.location.chromosome.{seqName,RefSeq}`,
  `short.called.variant.location.position`, `short.called.variant.location.refGenome.version`
- **Allele**: `short.called.variant.{ref,refCollapsed,alt,type}`
- **Calling QC**: `short.called.{alleleFrequency,readDepth}`,
  `short.called.filter.{text,others,countNoPASS}`, plus boolean filter flags
  (`PASS`, `cnv_undetermined`, `FVA_strong_requant`,
  `high_background_noise`, `homopolymer`, ...)
- **Gene/transcript**: `transcriptome.gene.{code,symbol}`,
  `transcriptome.transcript.{name,version,database,cdsLongest}`,
  `transcriptome.transcriptInPanel.{geneInPanel,labels.MANE,labels.MANE_PLUS}`,
  `short.annotated.transcriptSelect.{byFVT,mappedGenesInPanel}`
- **HGVS**: `short.annotated.transcriptContext.transcriptVariant.cnomen.base` (c.),
  `proteinVariant.pnomen.hgvsRefSeq` (p.)
- **Consequence**: `proteinVariant.consequence.sophiaName(Select)`, `trueIntergenic`
- **Population frequency**: `short.annotated.catalogs.{gnomadGenomes,gnomadExomes}.global.global.value`
- **ClinVar**: `short.annotated.catalogs.clinvar.{CLNREVSTAT,CLNSIG}`
- **In-house pathogenicity predictor (ABCD v2)**:
  `short_predictor.inhouse.predictors.ABCD.result.label`
- **User-annotation overlay** (the pathologist's flags):
  - `userAnnotations.interpretation.acmg.result.{classificationFinal,score,scoreFinal}`
  - `userAnnotations.account.pathogenicity.level`
  - `userAnnotations.interpretation.inReport.flagged`
  - `userAnnotations.account.{falsePositive,variantDescription}.flagged`
  - `userAnnotations.analysis.falsePositive.{id,etag,flagged}`
  - `userAnnotations.account.mrdMarker.*`

## Real FQL filter the panel uses

From the live request for SHORT_SUBSET, the gene-panel filter
(this is the actual filter Gen2 sends for the Hereditary Cancer panel):

```
fql:((transcriptome.gene.code anyOf (37370,23527,8298,5585,7006,32283,...,18889) 
      AND transcriptome.transcriptInPanel.geneInPanel = true) 
     OR (short.annotated.transcriptContext.proteinVariant.consequence.sophiaName = 'intergenic' 
         AND transcriptome.gene.symbol is empty))
AND short.called.filter.bool.PASS is true
```

83 gene codes in the panel. Sticking to these gene codes + `PASS=true` reproduces
the default Variants-tab subset for any case in this panel.

## Multi-query batch endpoint pattern

Some VQS POSTs send a multi-query body keyed by named slots
(e.g. `{"shortTotalCount": {...}, "retained": {...}}`) so the same call returns
a count plus a page of rows in one response. The doc only shows the
single-query shape; the SPA uses both. Worth supporting in our client.

## Counts visible on the Overview screenshot

(`screenshots/31_after_click.png`, on `interpretation-1047 / SG063-LPA`)

- 84 SNV / INDEL (off-target indicator)
- CNV: low called
- 3 quality indicators
- 38 warnings
- 170 inherited (manual annotation breakdown)

## What's still NOT captured (do during build, not now)

- Full row payload of `LAYER2_SHORT_SUBSET` with the 84 actual variants
  (the Overview-tab traffic only fetched aggregates and gene-views; the
  Variants tab will fetch rows the moment we click it).
- The exact request-body shape Gen2 sends when sorting/filtering in the
  Variants table (need this to reproduce the filter UX programmatically).
- The Report tab structure (what the existing PDF layout looks like).
