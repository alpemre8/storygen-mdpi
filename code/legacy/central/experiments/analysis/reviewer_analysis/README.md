# reviewer_analysis

Recompute deterministic A01–A10 reviewer analyses on immutable frozen inputs.

Protocol: REVIEWER_ANALYSES_P01B_V1 / 1.0.0. Scientific validity is UNVERIFIED until qualified separately.

Use `python reviewer_analysis.py plan`, then `preflight --config CONFIG --run-id FRESH_ID`, `run`, `status`, `verify`. Outputs belong only to the central experiment depot. Failed/interrupted IDs are retained; resume creates an explicitly linked fresh successor.

Pipeline: analyze. Exact dependencies are in dependencies.lock.yaml; scientific variables/controls/population/limitations are in experiment.yaml. Engine-specific validators and declared output JSON schemas are enforced; smoke execution does not validate scientific quality.
