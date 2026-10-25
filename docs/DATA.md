# Released data and provenance

All observations originate from existing experiments. No model was called to assemble this release. Transformations remove narrative text/headings and redundant file references; numeric measurements and historical statuses are retained. Per-file original/published hashes and transformations are in `provenance/SOURCE_MANIFEST.json`.

| Path | Grain and contents |
|---|---|
| `data/paper/tables/` | Recorded manuscript Tables 6–10 as CSV/LaTeX table fragments |
| `data/benchmark/` | Eight model/condition ledgers, each containing all 240 planned task IDs; eligibility, before/after MAE, TI, DA and failure reason |
| `data/tasksetv5/taskset_runtime.json` | Frozen task design, source/reference scene IDs, one selected feature per task and original file references; no scene prose |
| `data/original_features/` | Canonical per-scene numeric feature scores and measurement metadata for ten films; scene headings removed |
| `data/measurement_reliability/recorded.json` | All 500 repeated measurements (100 scenes × 5), scores, statuses, original summary statistics and runtime metadata |
| `data/e01/` | Selected actual canonical/independent E01 artifacts, feature measurements and recorded readiness/status evidence; excludes synthetic test archives |
| `data/e01_b/` | Nine measurement comparison cells, task-level records, archived uncertainty/agreement tables and limitations |
| `data/reviewer/` | Actual E02/E03/E04 numerical observations, result tables, confidence intervals and provenance manifests; prepared empty/not-run tables omitted |
| `data/e05_4_feature_diff/validated_numeric.json.gz` | 16,000 aligned scene slots, 1,920 planned task combinations and exclusions. Before/after retain only the five numeric feature scores |
| `data/e05_4_feature_diff/recorded_tables/` | Original feature-change, drift, interaction, pairing, direction and coverage tables |
| `data/e06/numeric_dataset.json.gz` | 240 task definitions and 1,920 model/condition rows. `B`, `T`, `A` are before, resampled target and after curves. `text_pairs` retains counts/ratios/status only |
| `data/e06/recorded_tables/` | Original canonical metrics and the thirty A01–A07 result tables |
| `provenance/HISTORICAL_RUNS.json` | Selected original run/index identities; wrapper/index entries are not independent experiments |

`metric_eligible` / `eligible` / `measurable` are the original contracts' eligibility flags; they are not interchangeable with model success or file count. Ineligible measurements remain missing and do not become zeros. All-attempt diagnostics explicitly count unsuccessful attempts in their denominator. TI and DA are fractions in [0,1]; printed paper tables express percentages. Positive gain `G = dB - dA` means movement toward the target. E05 deltas use `after - before` and describe feature change, not semantic preservation or human quality.

The main eight benchmark cells have valid-task counts 239/235 (Qwen2.5), 237/234 (Llama), 224/206 (Qwen3.5), and 239/238 (Gemma), in DP/CG order. The global intersection is 186; within-model pairing and E05's newly computed complete intersection are separate populations. The TasksetV5 design has 48 base intervals and 240 single-feature tasks; five tasks share each base, and scene overlap prevents treating all scene slots as independent samples.

`data/e01/E01A_independent_fp16/.../smoke_status.json` records the bounded independent qualification as **NOT_EXECUTED / HUMAN_RUN_PENDING** in that particular historical preparation. Its protocol and status are included without relabeling them as completed. The later historical full FP16 Gemma CG cell and the completed E01-B Q4 comparisons are distinct studies; they are not evidence that this bounded qualification was executed.

Some metadata and original source configs retain author-machine absolute paths. These are historical references, not paths required for public numeric replay. SHA-256 references to omitted artifacts are evidence of identity and do not imply that those artifacts are publicly available. `provenance/RESTRICTED_INPUTS.json` lists the verified historical E06 inputs needed to reconstruct the full private provenance chain without distributing their contents.
