# Paper-ready Evaluation V2.4 bundle

Paper analysis ID: `mdpi22_current4_v1`

This bundle is intentionally restricted to the metrics and tables used by the Paper-22 benchmark.

Canonical contents:

1. `VALIDATION_REPORT.json` — provenance/readiness checks.
2. `PAPER_RESULTS_SUMMARY.json` — machine-readable paper-facing results.
3. `tables/table6_global_common.*` — global-common cross-model TI/DA.
4. `tables/table7_within_model_paired.*` — paired coverage, TI and DA.
5. `tables/table8_primary_by_feature.*` — primary-model feature stratification.
6. `tables/table9_primary_by_length.*` — primary-model rewrite-length stratification.
7. `tables/table10_extractor_repeatability.*` — validated Feature Extraction V1.4 repeatability handoff.
8. `provenance/` — source artifacts, global-common IDs, reference-baseline selection and compact repeatability provenance.

Evaluation V2.4 computes only Target Improvement and threshold-free Directional Accuracy for rewrite performance. Mean absolute distance is retained internally only to decide Target Improvement. Coverage is reported separately. The feature-extractor repeatability table is validated/packaged from the upstream Feature Extraction V1.4 reliability artifact; it is not recomputed here.

