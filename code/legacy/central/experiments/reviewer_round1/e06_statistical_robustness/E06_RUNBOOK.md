# Human researcher runbook

Use the existing Python environment; no installation or model server.
All commands below use the implemented CLI. The real `run` command is reserved
for the human researcher. Preflight is read-only metadata inspection, not an
E06 scientific run. The implementation agent ran no real analysis.

```bash
E06=/home/alp-emre/projects/01-Storygen-area/storygen-experiment/experiments/reviewer_round1/e06_statistical_robustness/e06_statistical_robustness.py
E06_RUNS=/home/alp-emre/projects/01-Storygen-area/storygen-experiment-depot/experiments/reviewer_round1/e06_statistical_robustness/runs
```

1. Inventory and real-data metadata preflight:

```bash
python "$E06" inventory
python "$E06" preflight
```

Both commands check candidate hashes/metadata without canonical replay or
scientific calculations. PREFLIGHT_READY does not certify real results or text
alignment. A missing/changed bound artifact fails; do not edit frozen files or
weaken the binding to silence a discrepancy.

2. Full deterministic real analysis (HUMAN ONLY):

```bash
RUN="$E06_RUNS/$(date -u +%Y%m%dT%H%M%S%NZ)__e06_full_analysis"
python "$E06" run --human-run --output "$RUN" --pdf
```

`--pdf` attempts only an existing local pdflatex + IEEEtran installation. When
unavailable, complete source is produced and REPORT_STATUS.json records why no
PDF exists. No distribution/plugin/package is installed. Omitting --output
creates a unique microsecond UTC run ID automatically. Explicit real output
paths must remain in the central E06 run namespace. Existing IDs, including
failed/interrupted IDs, cannot be reused. Start a fresh ID after diagnosing any
failure; no automatic restart or historical regeneration occurs.

3. Optional second terminal, read-only progress monitor:

```bash
E06=/home/alp-emre/projects/01-Storygen-area/storygen-experiment/experiments/reviewer_round1/e06_statistical_robustness/e06_statistical_robustness.py
RUN=/home/alp-emre/projects/01-Storygen-area/storygen-experiment-depot/experiments/reviewer_round1/e06_statistical_robustness/runs/YOUR_ACTUAL_RUN_ID
watch -n 2 python "$E06" status --run "$RUN"
```

Replace YOUR_ACTUAL_RUN_ID with the exact directory printed by the first terminal.
For a short run a single terminal suffices. The runner prints stage/module,
completed/total units, percentage, elapsed and ETA. Times use HH:MM:SS. ETA is
unavailable before sufficient progress; fast stages may never have an ETA.
Machine-readable progress/events are in 08_logs/. Monitoring does not rewrite
any scientific output or start a model server.

4. Status inspection:

```bash
python "$E06" status --run "$RUN"
```

COMPLETE requires all seven modules and V01–V15 to pass. Independently review
E06_VALIDATION.json, provenance, failure ledgers, exact denominators and report.
Scientific validity is still SCIENTIFIC_RESULTS_NOT_YET_VERIFIED. Failed runs
remain intact with FAILED, INTERRUPTED or SCIENTIFIC_VALIDATION_FAILED status.

5. Report regeneration after a completed real run (optional; one is automatic):

```bash
python "$E06" report --run "$RUN" \
  --output "$RUN/07_report_$(date -u +%Y%m%dT%H%M%S%NZ)" --pdf
```

Report generation verifies source result seals and rejects incomplete scientific
runs and synthetic datasets. It uses persisted JSON/CSV results, not displayed
rounded tables, historical paper values or fixture numbers. A fresh report output
directory is mandatory. Do not overwrite the initial 07_report/.

Offline synthetic smoke test, safe for implementation work:

```bash
TMP_E06=$(mktemp -d /tmp/e06-fixture.XXXXXX)
python "$E06" dry-run --output "$TMP_E06/run" --pdf
python "$E06" status --run "$TMP_E06/run"
```

Synthetic reports are visibly marked SYNTHETIC FIXTURE and named
SYNTHETIC_REPORT.tex; the real report command refuses them. Keep these temporary
outputs outside Git. Source installation is not required; the primary runner
sets an isolated import path for the pinned evaluator. Any source-lock mismatch
requires developer investigation, never disabling the validator.
