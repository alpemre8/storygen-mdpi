# Evaluation V2.4 — Paper-22 scope (2.4.1)

Evaluation V2.4 is a deliberately reduced paper-facing block aligned to **Alp_Paper_MDPI-22**. New runs consume a frozen Taskset plus original and rewritten FeatureSets and do **not** run an LLM. Immutable `storygen.reanalysis-run/1.1` artifacts remain readable through the explicitly historical compatibility option.

The block computes exactly two rewrite-performance outcomes:

1. **Target Improvement (TI)** — whether mean absolute rewrite-to-target distance is smaller than source-to-target distance.
2. **Directional Accuracy (DA-sign-v1)** — task-macro sign agreement `sign(A-B) == sign(T-B)` over all selected aligned scene-feature points.

Mean absolute distance is retained only as the internal quantity needed to determine TI and to keep task-level calculations auditable. It is not exported as a separate paper benchmark score.

Coverage (valid/measurable task counts) is retained because the paper reports DP/CG valid counts and paired N. Coverage is not a performance metric.

## Explicitly removed from V2.4

The following V2.3 functionality is absent rather than merely hidden from the paper-ready ZIP:

- RMSE;
- Relative Improvement;
- Pearson correlation;
- DTW;
- TDS-v1 and all thresholded directional sensitivity logic;
- preservation/title/location/speaker/word-count diagnostics;
- permutation/sign-flip testing;
- Holm correction;
- McNemar testing;
- failure-penalty sensitivity scenarios;
- inferential p-values;
- public-release construction.

`statistics.py`, `directional_metrics.py`, `audit.py`, `public_release.py`, and their old CLIs are therefore not part of this block. Evaluation V2.4.1 adds only a narrow base-interval-clustered bootstrap as a supporting uncertainty analysis; it does not restore the removed V2.3 inferential/statistical suite.

## Figure selection is intentionally outside Evaluation V2.4

Evaluation V2.4 does **not** select, rank, package, or validate an illustrative Figure 2 example. Figure choice remains a manual paper-authoring decision. The paper-ready validator explicitly checks that no figure-selection artifact is present.

## Modular flow

```text
one condition evaluation (DP or CG)
    ↓
within-model paired summary
    ↓
cross-model global-common summary
    ↓
Paper-22-ready Tables 6–10 bundle

optional supporting analysis (separate artifact; no table overwrite)
```

Canonical CLIs:

- `cli/evaluate_run.py`
- `cli/build_paired_summary.py`
- `cli/build_cross_model_summary.py`
- `cli/build_paper_ready_bundle.py`
- `cli/validate_paper_ready_bundle.py`
- `cli/build_supporting_analysis.py`

## Output contracts

- evaluation run: `storygen.evaluation-run/2.4`
- paired summary: `storygen.paired-summary/2.4`
- cross-model summary: `storygen.cross-model-summary/2.4`
- paper-ready bundle: `storygen.paper-ready-bundle/2.4`

Canonical runtime IDs must contain `evv2_4` and remain direct children of the explicitly supplied external `<runs-root>/04-evaluation/`.

## 1. Evaluate one condition

```bash
export STORYGEN_EVALUATION_DEPOT_ROOT="$HOME/projects/storygen-evaluation-depot"

python evaluation/cli/evaluate_run.py \
  --taskset-runtime <taskset_runtime.json> \
  --feature-set-manifest <original_feature_set_manifest.json> \
  --candidate-feature-set <rewritten_feature_set_directory> \
  --output-root "$STORYGEN_EVALUATION_DEPOT_ROOT/runs/evaluation" \
  --output-run-id eval_evv2_4_<model>_<dp-or-cg>_v1 \
  --method DP-v1 \
  --rewrite-model <canonical-model-id>
```

Repeat for CG-v1 and for each rewrite model. Evaluation validates exact measurement-contract equality against the frozen Feature Extraction V1.4 manifest.

## 2. Build one-model paired summary

```bash
python evaluation/cli/build_paired_summary.py \
  --dp-run $STORYGEN_EVALUATION_DEPOT_ROOT/runs/evaluation/eval_evv2_4_<model>_dp_v1 \
  --cg-run $STORYGEN_EVALUATION_DEPOT_ROOT/runs/evaluation/eval_evv2_4_<model>_cg_v1 \
  --taskset-runtime <taskset_runtime.json> \
  --output $STORYGEN_EVALUATION_DEPOT_ROOT/runs/evaluation/paired_evv2_4_<model>_v1
```

The paired artifact contains only:

- DP valid count;
- CG valid count;
- paired intersection N;
- DP/CG TI;
- DP/CG DA;
- the same TI/DA stratified by feature and rewrite length.

No inferential statistics are computed.

## 3. Build global-common cross-model summary

```bash
python evaluation/cli/build_cross_model_summary.py \
  --model-pair qwen2.5-7b-q4 <qwen-dp> <qwen-cg> \
  --model-pair llama3.1-8b-instruct-gguf <llama-dp> <llama-cg> \
  --model-pair qwen3.5-9b-gguf <qwen35-dp> <qwen35-cg> \
  --model-pair gemma3-12b-it-gguf <gemma-dp> <gemma-cg> \
  --analysis-set-id current4_v1 \
  --taskset-runtime <taskset_runtime.json> \
  --output $STORYGEN_EVALUATION_DEPOT_ROOT/runs/evaluation/cross_evv2_4_current4_v1
```

The intersection contains only task IDs measurable in every supplied model-condition combination. Each row reports only TI and DA on that identical denominator.

## 4. Build deterministic supporting uncertainty

The supporting CLI reads existing Evaluation V2.4 task records. It does not run an LLM, does not change TI/DA definitions or denominators, and does not write into the paper-ready Tables 6–10 bundle. The canonical Paper-22 bootstrap resamples `base_interval_id` clusters with replacement, uses 10,000 resamples and seed 42, and reports percentile 95% intervals for Gemma CG-v1 minus DP-v1 TI and DA differences. Optional paired-summary inputs also export descriptive CG-v1 minus DP-v1 point differences for the four models.

```bash
python evaluation/cli/build_supporting_analysis.py \
  --dp-run $STORYGEN_EVALUATION_DEPOT_ROOT/runs/evaluation/eval_evv2_4_gemma3_12b_q4km_dp_v1 \
  --cg-run $STORYGEN_EVALUATION_DEPOT_ROOT/runs/evaluation/eval_evv2_4_gemma3_12b_q4km_cg_v1 \
  --taskset-runtime <taskset_runtime.json> \
  --output $STORYGEN_EVALUATION_DEPOT_ROOT/runs/evaluation/supporting_evv2_4_gemma3_paper22_v1 \
  --bootstrap-resamples 10000 \
  --seed 42 \
  --paper22-lock
```

`--paper22-lock` checks the rounded frozen manuscript values and exits non-zero if the supporting calculation does not reproduce them. Supporting outputs are written only to the explicit output directory.

## 5. Build the Paper-22-ready ZIP

Copy `config/paper_analysis_plan_example.yaml`, set the actual artifact paths, and run:

```bash
python evaluation/cli/build_paper_ready_bundle.py \
  --plan $STORYGEN_EVALUATION_DEPOT_ROOT/runs/evaluation/paper_plan_evv2_4_mdpi22_v1.yaml \
  --output $STORYGEN_EVALUATION_DEPOT_ROOT/runs/evaluation/paper_ready_evv2_4_mdpi22_v1
```

The builder creates a sibling `.zip` and outputs only:

```text
README.md
MANIFEST.json
VALIDATION_REPORT.json
PAPER_RESULTS_SUMMARY.json

tables/
├── table6_global_common.csv/.tex
├── table7_within_model_paired.csv/.tex
├── table8_primary_by_feature.csv/.tex
├── table9_primary_by_length.csv/.tex
└── table10_extractor_repeatability.csv/.tex

provenance/
├── SOURCE_ARTIFACTS.json
├── GLOBAL_COMMON_TASK_IDS.json
├── REFERENCE_BASELINE.json
└── EXTRACTOR_REPEATABILITY_SUMMARY.json
```

There is **no** figure-selection directory or Figure 2 artifact.

### Table 10 handoff

Table 10 is not recomputed by Evaluation V2.4. The paper plan points to the canonical Feature Extraction V1.4 repeatability summary. Before packaging, Evaluation V2.4 requires the Paper-22 audit identity (100 scenes × 5 repeats = 500 requests, 500 valid, zero schema/measurement failure) and exact measurement identity match with the benchmark feature extractor.

## Validation

```bash
python -m compileall -q evaluation/src evaluation/cli evaluation/tests
python -m pytest -q evaluation/tests
```

The paper-ready validator checks artifact hashes, V2.4 contracts, common taskset/measurement provenance, exact cross-model source evaluations, the repeatability handoff, absence of removed legacy metric keys in paper-facing JSON/CSV, and absence of figure-selection artifacts. Supporting bootstrap artifacts are separate and are never injected into Tables 6–10.

All condition-evaluation commands must pass an explicit external `--output-root`; paper/summary outputs are also explicit paths.

## P01A integrity repair (Evaluation scientific contract remains 2.4.1 / 2.4)

TI, DA, eligibility, paired/common populations and the default MT19937 bootstrap
are unchanged. Aggregation accepts either historical `feature_set_manifest` or
active `reference_feature_set_manifest`; conflicting aliases, missing identities,
incompatible measurement hashes and a different supplied runtime are rejected.
The original/reference measurement contract, source rewrite, task selections,
canonical B/T curves and rewritten text lineage are validated before outputs are
created or an existing output is removed. Active candidate measurement equality
remains a full contract comparison.

Earlier historical runtimes have different raw hashes and metadata. Historical
read compatibility requires resolving the recorded runtime by its exact content
hash, independently verifying its FeatureSet/protocol bindings, and comparing
the ordered Taskset owner's structure projection (including film/scene IDs,
feature, variant, interval, pair and base interval). Aggregation still requires
the exact runtime SHA recorded in the Evaluation manifests. No version bump or
new metric/eligibility contract is introduced.

All four deterministic CLIs accept `--artifact-paths paths.json`. The JSON object
maps each **recorded file path** to one explicit local file path. For run-directory
references, use the complete recorded manifest file path as the key. Every file
is checked against the recorded SHA-256; no automatic depot scanning occurs.
Duplicate keys, multiple targets, missing files and wrong hashes are errors.
Successful evaluations record both declared and resolved paths in
`integrity_validation.resolved_artifacts`. Frozen manifests are never rewritten.

The separately recovered manuscript Table A6 procedure is available by explicit
`--rng-engine numpy-pcg64` on `build_supporting_analysis.py`. It requires the
optional `manuscript` dependency (NumPy >=1.22,<3), resets PCG64 with seed 42 for
each model, sorts represented base-interval IDs, samples clusters with replacement,
weights all paired tasks in each sampled cluster, and uses linear percentiles.
The default `python-mt19937` procedure and the historical `--paper22-lock` values
are preserved. The lock still fails on the actual frozen Gemma result; it is a
historical comparison, not a validator for the October manuscript Table A6.
The manuscript procedure must be selected explicitly; validation without the
lock certifies execution, not historical manuscript provenance.

## Author-approved Table A6 protocol — 2026-10-10

The author adopted the independently verified PCG64 procedure for the revised
manuscript and retained the published Table A6 values. The frozen specification
is [config/table_a6_pcg64_v1.json](config/table_a6_pcg64_v1.json), with a companion
SHA-256 file and [author decision](config/TABLE_A6_AUTHOR_DECISION.md). It records
the exact original input hashes, ordered paired populations, sorted 48-cluster
enumerations, implementation source identities and independent verification.
Select `--rng-engine numpy-pcg64 --bootstrap-resamples 10000 --seed 42
--confidence-level 0.95` for each model independently.

This scientific adoption does not confirm the recovered legacy script's
historical use. That execution provenance remains UNVERIFIED. The old default
MT19937 procedure and Paper-22 lock are preserved; the proposed MT19937 numerical
correction is not adopted. Evaluation 2.4.1 / contract 2.4 metric and eligibility
semantics remain unchanged. The approved analysis has its own versioned protocol
identity `table-a6-pcg64-v1` and contract 1.0. Future source or configuration
changes need a new recorded protocol revision rather than silent replacement.

Reviewer phase completion uses a local annotated phase tag `p01a-pass`, separate
from repository/scientific release versions. It records approved scientific
reproducibility while retaining historical execution uncertainty.
