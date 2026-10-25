# Experiments

Generated from owner manifests, exact locks and sealed run metadata. Migration verification and synthetic runs are separate from research results.

## Reviewer Round 1 (E01–E05)

- [e01_canonical_mistral](experiments/reviewer_round1/e01_canonical_mistral/e01_canonical_mistral.py) — Does changing only the canonical measurement model alter existing rewrite measurements? [Protocol/docs](experiments/reviewer_round1/e01_canonical_mistral/README.md) · [exact locks](experiments/reviewer_round1/e01_canonical_mistral/dependencies.lock.yaml). Owner: `storygen-feature-extraction`. Stages: remeasure_dp → remeasure_cg. Research runs: none in new namespace. Migration verification: 1 complete. Scientific validity: **UNVERIFIED**.
- [e01_independent_extractor](experiments/reviewer_round1/e01_independent_extractor/e01_independent_extractor.py) — How does the strict independent F16 extractor behave on the locked bounded sample? [Protocol/docs](experiments/reviewer_round1/e01_independent_extractor/README.md) · [exact locks](experiments/reviewer_round1/e01_independent_extractor/dependencies.lock.yaml). Owner: `storygen-feature-extraction`. Stages: qualify. Research runs: none in new namespace. Migration verification: 1 complete, 1 failed. Scientific validity: **UNVERIFIED**.

## Feature Measurement and Reliability

- [measurement_reliability](experiments/measurement/measurement_reliability/measurement_reliability.py) — How repeatable is canonical measurement on the fixed 100-scene study? [Protocol/docs](experiments/measurement/measurement_reliability/README.md) · [exact locks](experiments/measurement/measurement_reliability/dependencies.lock.yaml). Owner: `storygen-feature-extraction`. Stages: reliability. Research runs: none in new namespace. Migration verification: none. Scientific validity: **UNVERIFIED**.
- [original_feature_extraction](experiments/measurement/original_feature_extraction/original_feature_extraction.py) — Measure original screenplay scenes with the frozen canonical instrument. [Protocol/docs](experiments/measurement/original_feature_extraction/README.md) · [exact locks](experiments/measurement/original_feature_extraction/dependencies.lock.yaml). Owner: `storygen-feature-extraction`. Stages: measure. Research runs: none in new namespace. Migration verification: none. Scientific validity: **UNVERIFIED**.

Historical results stay in their original depots; exact read-only locators live in `catalogs/experiment_architecture_v1/legacy.jsonl`. A completed migration smoke is not a paper result.

Use `python tools/experiments.py list`, `show ID`, `doctor ID`, or the owner `plan/preflight/run/status` commands. Bound doctor requires `--config` and a fresh `--run-id`.

Create an independent experiment with `python tools/new_experiment.py --spec SPEC.json`. Compatible frozen stages are selected by exact version; only the studied behavior belongs in a new owned engine. See [creation guide](docs/architecture/EXPERIMENT_CREATION_GUIDE.md).
