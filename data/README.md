# Example Variant Table

Live snapshot from the Sophia DDM hackathon test account, pulled with [`scripts/vqs_query.py`](../scripts/vqs_query.py).

**Source**
- `analysisId`: `200042360`
- `interpretationId`: `interpretation-1042`
- `experimentTypeId`: `126000`
- `transformers`: `FLATTEN,SHORT_SUBSET`
- Captured: 2026-05-09

**Contents**
- [`variants_demo_full.tsv`](variants_demo_full.tsv) — 333 rows × 524 columns. Tab-separated; nested fields are JSON-encoded into the cell.
- [`variants_demo_full.json`](variants_demo_full.json) — same data, raw API response (preserves nested structure).
- [`variants_demo_slim.tsv`](variants_demo_slim.tsv) — 333 rows × 14 hand-picked columns (gene, transcript, position, type, c./p. nomenclature, allele frequency, read depth, gnomAD frequencies, ClinVar). Easy to open in Excel.

**At a glance**
- 31 distinct genes, all classic hereditary-cancer susceptibility genes.
- Top 5: BRCA1 (38), BRCA2 (28), ATM (27), APC (24), BARD1/MSH2/PMS2 (22 each).
- 276 SNVs, 57 INDELs.

**Heads up — user-annotation columns are absent here.**
With only `FLATTEN,SHORT_SUBSET` transformers, you don't get ACMG classification, pathogenicity flags, or `inReport` flags. To pull those, add `USER_ANNOTATIONS,USER_ANNOTATIONS_REFRESH,PHENOTYPIC_RANKING,PHENOTYPIC_RANKING_REFRESH` to the transformer chain (see the production cURL in [`../docs/VQS-API.md`](../docs/VQS-API.md)).
