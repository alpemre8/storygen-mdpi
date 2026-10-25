# e03_dp48_extension

Extend the frozen DP population to DP48 without regenerating original DP12 or CG observations.

Protocol: E03_DP48_EXTENSION_V1 / 1.0.0. Scientific validity is UNVERIFIED until qualified separately.

Use `python e03_dp48_extension.py plan`, then `preflight --config CONFIG --run-id FRESH_ID`, `run`, `status`, `verify`. Outputs belong only to the central experiment depot. Failed/interrupted IDs are retained; resume creates an explicitly linked fresh successor.

Pipeline: prepare → preflight → generate_extension → validate_extension → remeasure_extension → evaluate_extended. Exact dependencies are in dependencies.lock.yaml; scientific variables/controls/population/limitations are in experiment.yaml. Engine-specific validators and declared output JSON schemas are enforced; smoke execution does not validate scientific quality.
