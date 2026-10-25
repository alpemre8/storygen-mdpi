# Exact researcher commands

Run from the repository using the existing environment; install nothing.

```bash
cd /home/alp-emre/projects/01-Storygen-area/storygen-experiment
export PATH="$PWD/experiments/reviewer_round1/e05_4_feature_diff:$PATH"
```

Read-only preflight (no run allocated, one available task inspected per combination,
full frozen definitions and all global instrument/lineage manifests checked):

```bash
e05-feature-diff preflight --run-id e05fd_research_001
```

After reviewing the bindings/protocol, the researcher starts the full real analysis:

```bash
e05-feature-diff run --run-id e05fd_research_001
```

This runs one bounded deterministic CPU analysis and stops. No server, GPU model,
second terminal or inference is needed. If no ID is supplied, run/preflight print
a new UTC timestamp plus random suffix. A preflight ID can be reused for the actual
run because preflight does not allocate it. A run ID is create-only; an allocated,
failed, interrupted or sealed ID is never reused or overwritten.

```bash
e05-feature-diff status --run-id e05fd_research_001
e05-feature-diff report --run-id e05fd_research_001
e05-feature-diff verify --run-id e05fd_research_001
```

Status/report may omit the ID only when exactly one run directory exists for this
experiment. Otherwise they reject ambiguous selection. `report` verifies the
central seal and prints the existing report path; it does not regenerate artifacts.
An explicit run ID is recommended even when only one run exists.

The stage log reports processed/complete/partial/missing/invalid tasks and observed
validation throughput, elapsed HH:MM:SS and ETA HH:MM:SS. ETA starts UNKNOWN.
The central runner additionally reports stage progress and full-run elapsed time.

Equivalent central contract and artifact verification:

```bash
/home/alp-emre/.venv/bin/python3 tools/experiments.py plan e05_4_feature_diff --config experiments/reviewer_round1/e05_4_feature_diff/run.example.json --run-id e05fd_research_001
/home/alp-emre/.venv/bin/python3 tools/experiments.py preflight e05_4_feature_diff --config experiments/reviewer_round1/e05_4_feature_diff/run.example.json --run-id e05fd_research_001
/home/alp-emre/.venv/bin/python3 tools/experiments.py verify e05_4_feature_diff --run-id e05fd_research_001
/home/alp-emre/.venv/bin/python3 tools/experiments.py artifacts e05_4_feature_diff --run-id e05fd_research_001
```

The public wrapper adds experiment-specific bounded input validation before central
preflight/run. Direct central PREPARE performs full hash/lineage validation as well.
The config has explicit purpose RESEARCH, and central policy requires committed
exact implementation sources. No new run is reserved by preflight.

## Offline verification only

```bash
/home/alp-emre/.venv/bin/ruff check experiments/reviewer_round1/e05_4_feature_diff
/home/alp-emre/.venv/bin/ruff format --check experiments/reviewer_round1/e05_4_feature_diff
/home/alp-emre/.venv/bin/python3 -m pytest -q --import-mode=importlib tests experiments/reviewer_round1/e05_4_feature_diff/tests
```

For deliberate future edits of this experiment only, refresh owned locks through
the same supported central runtime SHA/atomic-write/contract APIs used by creation:

```bash
/home/alp-emre/.venv/bin/python3 experiments/reviewer_round1/e05_4_feature_diff/refresh_owned_locks.py
```

The creation receipt remains unchanged; implementation_lock_receipt.json records
refreshed owned bytes. This is not an input rebinding, package install, historical
artifact edit or scientific qualification. No broader lock refresh is performed.

## Artifact locations

Run root:

`/home/alp-emre/projects/01-Storygen-area/storygen-experiment-depot/experiments/reviewer_round1/e05_4_feature_diff/runs/<RUN_ID>/`

Researcher tables, plots and reports: `stages/report/raw/` below that root.
Full-precision numerical tables: `stages/analyze/raw/analysis.json`.
Input provenance: `stages/report/raw/input_provenance.json`.
Central exact execution sources/environment: `run.lock.json`.
Authoritative immutable manifest/seal: `run_manifest.json`, `integrity/SEALED.json`.
A report-local `artifact_manifest.json` hashes its deliverables except itself;
the central seal covers that manifest and all intermediate/operational artifacts.

No real scientific output belongs in the source repository. Offline synthetic
fixture artifacts are created only in pytest temporary directories. Keep the
existing environment and frozen inputs; do not silently fall back to other runs.
