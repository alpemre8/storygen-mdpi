# Implementation report

Experiment **E05-4-FEATURE-DIFF** (`e05_4_feature_diff`), protocol
`E05_4_FEATURE_DIFF_V1` / `1.0.0`, public runner **e05-feature-diff**.

## Readiness boundaries

- **IMPLEMENTATION_READY**: registered through the official central creator;
  independent four-stage pipeline, schemas, numerical code, exports and CLI exist.
- **INPUT_BINDINGS_READY**: all eight authoritative historical manifest chains and
  exact per-task file bindings are frozen. Bounded read-only validation passes;
  full record-level eligibility remains for the researcher-run VALIDATE stage.
- **OFFLINE_TESTS_PASSED**: 113 tests passed (53 central + 60 experiment-owned),
  including synthetic numerical/report fixtures and immutable central lifecycle.
- **REAL_ANALYSIS_COMPLETE**: **FALSE**. No full real pipeline was executed.
- **SCIENTIFIC_VALIDITY_VERIFIED**: **FALSE**. Execution and synthetic tests do not
  independently validate the historical instrument, semantics or human agreement.

No LLM calls, model loading, server startup, rewrite, extraction, reanalysis,
package installation, new real scientific reports or real-run output allocation
were performed. Existing E05 variants and historical data were not modified.

## Architecture and files

All new experiment files are under
`experiments/reviewer_round1/e05_4_feature_diff/`:

| Files | Responsibility |
|---|---|
| `experiment.yaml`, `pipeline.yaml` | Official independent research registration and PREPARE → VALIDATE → ANALYZE → REPORT contracts |
| `creation_receipt.json` | Original central creator receipt, preserved unchanged |
| `dependencies.lock.yaml`, `implementation_lock_receipt.json`, `refresh_owned_locks.py` | Exact owned source/assets and installed package locks, refreshed through central SHA/contract/atomic-write APIs |
| `e05-feature-diff`, `e05_4_feature_diff.py`, `run.example.json` | Local executable, central primary, explicit RESEARCH configuration; preflight/run/status/report/verify |
| `src/common.py` | Frozen five-feature, ID, epsilon, hashing, finite-number and create-only serialization contracts |
| `src/bindings.py` | Exact immutable file loading, original/rewrite/reanalysis lineage, full TasksetV5 population and eight-combination construction |
| `src/validate.py` | Scene/task identity/order, instrument compatibility, coverage and explicit task/scene exclusions |
| `src/analyze.py` | Scene differences, complete-task means/medians/direction counts and separate target/non-target metrics |
| `src/aggregate.py` | Equal-task matrices, direction strata, drift distributions, DP/CG and all-eight intersections, base-cluster bootstrap |
| `src/report.py` | Required CSVs, five matrix-statistic datasets, 19 panels in PNG/PDF, computed reports, provenance and artifact hashes |
| `src/engine.py` | Four central local-engine stage entry points and bounded read-only binding check |
| `src/assets/bindings.json` | Exact physical historical paths/hashes, missing roles, instrument and source-release identities; metadata only |
| `src/assets/schemas/{prepare,validate,analyze,report}.schema.json` | Versioned stage payload schemas; pipeline enforces exact full-population task/scene counts |
| `tests/conftest.py`, `tests/test_numerics.py`, `tests/test_protocol.py` | Synthetic numeric fixtures, domain tests, generated registration conformance |
| `README.md`, `SCIENTIFIC_PROTOCOL.md`, `INPUT_BINDINGS.md`, `COMMANDS.md`, this file | Research protocol, data inventory, reproducibility and implementation evidence |

The only shared-source change is the new catalog entry in `EXPERIMENTS.md`.
The pre-existing catalog modifications were preserved and excluded from staging.
No generic framework changes or cross-experiment private imports were needed.

## Actual historical binding inventory

| Model | DP-v1 available rewrite/reanalysis files | CG-v1 available rewrite/reanalysis files |
|---|---:|---:|
| Qwen2.5-7B | 239 / 239 | 235 / 235 |
| Llama-3.1-8B | 237 / 237 | 234 / 234 |
| Qwen3.5-9B | 224 / 224 | 206 / 206 |
| Gemma-3-12B | 239 / 239 | 238 / 238 |

These counts agree with the archived completion manifests. There are 68 historical
missing task outputs among 1920 planned records. They do not establish new complete
measurement counts, scene eligibility or the actual all-eight common set. Those
results are deliberately not calculated during implementation. Missing file roles
and task IDs are explicit in INPUT_BINDINGS.md and the hash-bound metadata asset.
Task definitions and transfer plans exist for all tasks, including failed rewrites.

Canonical originals and after measurements declare the same complete Qwen
measurement configuration. Per-task reanalysis attests the compact-JSON hash of
both rewritten scenes and the transfer plan, not merely a same-named task file.
That attestation is checked together with the global manifest chain.

The frozen Taskset has no single target-direction field: archived transfer plans
assign directions per scene. Heterogeneous intervals are labeled MIXED and retain
scene-level INCREASE/DECREASE/MAINTAIN strata. This avoids invented task directions
or interpreting signed cancellation as no movement.

## Actual offline verification

Commands were run with the existing `/home/alp-emre/.venv/bin/python3` and installed
ruff; no installations/downloads were required.

```text
python3 -m pytest -q --import-mode=importlib tests experiments/reviewer_round1/e05_4_feature_diff/tests
113 passed in 35.96s

python3 -m pytest -q --import-mode=importlib experiments/reviewer_round1/e05_4_feature_diff/tests
60 passed in 7.92s

ruff check experiments/reviewer_round1/e05_4_feature_diff
All checks passed!

ruff format --check experiments/reviewer_round1/e05_4_feature_diff
All files formatted

Central preflight with explicit offline configuration:
PLAN_READY; contracts/source/environment/fresh-run namespace checks passed.

Experiment bounded binding-check:
INPUT_BINDINGS_READY; 1920 planned records, 16000 scene slots.

Central catalog --check:
PASS; existing catalog content preserved except new experiment row.
```

The domain tests cover all thirty requested categories: schema, scene alignment,
full frozen-population shape/enumeration/accounting, signed/absolute change,
epsilon without value mutation, target/non-target identification, within-task
means and equal-task matrices, unequal lengths and signed cancellation, missing
rewrite/reanalysis, partial intervals, invalid/nonfinite values, mixed protocols,
wrong identities/order, duplicate scene/task records, exact DP/CG and all-eight
intersections, repeated-base dependence and deterministic bootstrap, CSV nulls,
empty groups, deterministic order, immutable output/sealing and absent inference
paths. Additional tests cover reanalysis input hash lineage, malformed JSON numeric
tokens, source order, optional plotting imports and public CLI path rejection.

Synthetic report smoke tests generated all ten required numbered CSVs, the five
statistic-specific matrix CSVs, three Markdown reports, summary/provenance/manifest,
and **38 image files** (19 panels × PNG/PDF), exclusively in pytest temporary
directories. Numerical assertions and output hashes passed. Example heatmap and
direction panels were visually inspected; gray/NA cells distinguish missing data
from zero and axes/legends are consistent. These are test fixtures, not research
results, and are not committed or copied into the scientific depot.

## Known limits and researcher responsibility

Complete coverage, exclusions, paired/global intersections and numerical findings
remain unknown until the explicit researcher-run analysis. Every real scientific
report is therefore **NOT YET GENERATED FROM A REAL FULL RUN**.

Source measurement constructs and human agreement remain unverified. Historical
missingness can affect comparisons; the shared Qwen instrument and historical
DP/CG prompt differences remain explicit. Bootstrap intervals are descriptive,
withheld below eight bases, and do not remove overlapping-window or film dependence.
No film-cluster sensitivity is implemented. Optional plotting import failure
preserves tables and records the blocker; installed dependencies remain exactly
version-locked. Local raw scientific artifacts are not backed up by source Git.

Git source commit and push status are reported in the final delivery and can be
verified with `git log -1` / `git status`. A document cannot embed its own final
commit hash without changing that identity. Only experiment files and its catalog
entry are included; the user's existing catalog changes remain in the working tree.
