# Validation — Evaluation V2.4

V2.4.1 must preserve these invariants:

- Rewrite performance has exactly two paper outcomes: Target Improvement and `DA-sign-v1`.
- `DA-sign-v1` is threshold-free: `sign(A-B) == sign(T-B)` over every aligned selected point, task-macro aggregated.
- Mean absolute distance is internal to Target Improvement, not an independent paper score.
- Coverage counts remain available for Table 7 but are not benchmark scores.
- Within-model scores use the exact DP-v1/CG-v1 measurable-task intersection.
- Absolute cross-model scores use the exact all-condition global-common measurable-task intersection.
- The Feature Extraction V1.4 repeatability result is validated/packaged, never recomputed in evaluation.
- Paper-ready output contains Tables 6–10 only for evaluation-facing paper results.
- Base-interval-clustered bootstrap is supporting-only, reads already computed Evaluation V2.4 task records, and never changes Tables 6–10 or the paper-ready bundle.
- Historical Paper-22 supporting bootstrap uses `base_interval_id`, 10,000 resamples, seed 42, and percentile 95% intervals.
- The author-approved revised-manuscript Table A6 protocol is frozen in `config/table_a6_pcg64_v1.json` and its companion checksum: PCG64 / `numpy.random.default_rng(42)`, 48 clusters, 10,000 resamples, an independent reset per model and 95% linear percentile intervals over the original paired populations.
- Approved scientific reproducibility does not confirm historical execution provenance. That provenance remains explicitly UNVERIFIED; the old Paper-22 lock and historical MT19937 artifacts remain unchanged.
- Permutation/sign-flip tests, Holm correction, McNemar tests, inferential p-values, failure-penalty sensitivity, RMSE, RI, Pearson, DTW, TDS-v1, preservation diagnostics, and the public-release builder remain absent.
- No figure selection, ranking, or Figure 2 artifact is produced.
- Other project blocks are not modified by this patch.

Run:

```bash
python -m compileall -q evaluation/src evaluation/cli evaluation/tests
python -m pytest -q evaluation/tests
```
