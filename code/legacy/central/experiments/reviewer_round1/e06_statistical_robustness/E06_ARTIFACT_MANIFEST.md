# E06 artifact manifest

Central namespace:
`storygen-experiment-depot/experiments/reviewer_round1/e06_statistical_robustness/runs/<unique-id>/`.
No historical output is overwritten. Source data remain in original depots.

| Location | Content |
|---|---|
| E06_MANIFEST.json | Protocol, dataset kind, creation timestamp, input binding, zero inference requests |
| E06_STATUS.json | Technical/scientific gate status and explicit seven-module states |
| E06_PROVENANCE.json | Exact consumed paths, SHA-256 hashes, absences and resolved historical references |
| E06_VALIDATION.json | All V01–V15 outcomes and evidence |
| E06_RESULTS_SUMMARY.json / .md | Computed status/population summaries; independent validity remains unverified |
| E06_REVIEWER_COVERAGE.md | Precise partial reviewer mapping |
| 00_manifest/ | Implementation source identities and computed RESULT_SEAL.json |
| 01_preflight/ | Metadata-only inventory receipt |
| 02_canonical_metrics/ | Text-free per-task metrics and exact replay compatibility receipt |
| 03_analyses/A01–A07/ | Required module artifacts below |
| 04_cross_validation/ | Copy of scientific validation record |
| 05_tables/ | Complete computed Markdown companion tables |
| 06_figures/ | Explicit no-figures note; tables supply all quantitative evidence |
| 07_report/ | IEEEtran source, full companion tables, reviewer coverage, report/PDF status |
| 08_logs/ | Atomic progress snapshot and append-only deterministic-stage event log |

Required module filenames (all implemented, including empty tables with explicit
module status when inputs are unavailable):

- A01_RESULTS.csv, A01_RESULTS.json, A01_DIRECTION_BREAKDOWN.csv,
  A01_LLAMA_MAINTAIN_ANALYSIS.csv, A01_SUMMARY.md.
- A02_DIRECTION_DISTRIBUTION.csv, A02_BASELINE_RESULTS.csv,
  A02_BASELINE_RESULTS.json, A02_FEATURE_BREAKDOWN.csv, A02_SUMMARY.md.
- A03_ALL_ATTEMPT_DA.csv, A03_FAILURE_LEDGER.csv, A03_RESULTS.json, A03_SUMMARY.md.
- A04_GLOBAL_COMMON_TASKS.csv, A04_EXCLUDED_TASKS.csv, A04_MISSING_OBSERVATIONS.csv,
  A04_FEATURE_BREAKDOWN.csv, A04_LENGTH_BREAKDOWN.csv,
  A04_DIRECTION_BREAKDOWN.csv, A04_RESULTS.json, A04_SUMMARY.md.
- A05_FEATURE_LEVEL_RESULTS.csv, A05_FEATURE_LEVEL_RESULTS.json,
  A05_TI_MATRIX.csv, A05_DA_MATRIX.csv, A05_ALL_ATTEMPT_MATRIX.csv, A05_SUMMARY.md.
- A06_TASK_LENGTH_RATIOS.csv, A06_SCENE_LENGTH_RATIOS.csv,
  A06_MODEL_CONDITION_SUMMARY.csv, A06_LENGTH_BREAKDOWN.csv,
  A06_RESULTS.json, A06_SUMMARY.md.
- A07_THRESHOLD_RESULTS.csv, A07_GAIN_DISTRIBUTION.csv,
  A07_RESULTS.json, A07_SUMMARY.md.

Additional computed artifacts: A02_MODEL_DA_COMPARISON.csv,
A04_SCREENPLAY_BREAKDOWN.csv, A04_SCENE_DIRECTIONS.csv,
A05_DP_CG_COMPARISONS.csv, A06_SCENE_DISTRIBUTION.csv and
A06_DP_CG_COMPARISONS.csv. These stay within the seven modules; there is no A08.
Each module JSON includes all its table rows, explicit denominator, status and
module-specific scientific caveats. No screenplay contents are exported.

IEEE report has all 17 requested sections, bounded aggregate table slices and
full companion tables. Very large task/scene ledgers are referenced rather than
printed as hundreds of narrative pages. Optional PDF is available only with the
existing local IEEEtran toolchain. No such local compiler was found at handoff;
source generation was tested and PDF is marked unavailable on fixture smoke.
