# Patch history

## E06-P001 — Seven-module deterministic reviewer analysis (2026-10-18)

Scope: new centrally owned E06_V1 experiment; no frozen engine, E01–E05,
TasksetV5, measurement or historical depot changes.

Files: e06_statistical_robustness.py; experiment.yaml; pipeline.yaml;
dependencies.lock.yaml; historical_binding.json; provider_sources.json;
run.example.json; src/{common,loader,analyses,reporting,pipeline,cli,fixtures,launch}.py;
src/assets/synthetic_request.json; tests/{historical_fixture,test_e06,test_cli}.py;
README.md; SOURCE_INVENTORY.md; E06_{EXPERIMENT_DESIGN,DATA_CONTRACT,
METRIC_DEFINITIONS,REVIEWER_COVERAGE,RUNBOOK,VALIDATION_PROTOCOL,
ARTIFACT_MANIFEST}.md; IMPLEMENTATION_HANDOFF.md; IMPLEMENTATION_STATUS.json;
this patch_history.md.

Reason: implement the seven bounded reviewer-requested robustness diagnostics
using exact canonical evaluator/provenance reuse and immutable historical inputs.
Protect task-macro weighting, explicit failures, source identities, threshold
boundaries and the human researcher's exclusive authority to execute real E06.

Validation: 80 E06 offline synthetic tests; 53 existing central framework tests;
Ruff; source locks; metadata-only historical preflight; direct CLI fixture dry-run,
status and report source generation; optional DAG adapter fixture smoke. No
historical scientific E06 run, inference, package installation or model execution.
PASS subject to the final verification receipt in IMPLEMENTATION_STATUS.json.

Limitations: real canonical compatibility, actual eligible counts/intersections
and source/rewrite alignment remain unverified until human execution. No local
IEEEtran/PDF toolchain; LaTeX source is available without installation. Descriptive
summaries do not establish uncertainty, human validation, semantic preservation,
dramaturgical quality or a numerical-guidance causal effect. The pre-existing
EXPERIMENTS.md worktree edits are excluded from this patch and commit.
