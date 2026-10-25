# e03_repeatability

How repeatable are the frozen CG/DP generation and measurement protocols across five repetitions?

Protocol: E03_REPEATABILITY_V1 / 1.0.0. Scientific validity is UNVERIFIED until qualified separately.

Use `python e03_repeatability.py plan`, then `preflight --config CONFIG --run-id FRESH_ID`, `run`, `status`, `verify`. Outputs belong only to the central experiment depot. Failed/interrupted IDs are retained; resume creates an explicitly linked fresh successor.

Pipeline: prepare → preflight → generate_cg → generate_dp → validate_generation → remeasure → evaluate. Exact dependencies are in dependencies.lock.yaml; scientific variables/controls/population/limitations are in experiment.yaml. Engine-specific validators and declared output JSON schemas are enforced; smoke execution does not validate scientific quality.
