# e02_no_guidance

Does no-guidance generation change the frozen 48-base / 240-evaluation comparison?

Protocol: E02_MIN_NG_V0 / 1.0.0. Scientific validity is UNVERIFIED until qualified separately.

Use `python e02_no_guidance.py plan`, then `preflight --config CONFIG --run-id FRESH_ID`, `run`, `status`, `verify`. Outputs belong only to the central experiment depot. Failed/interrupted IDs are retained; resume creates an explicitly linked fresh successor.

Pipeline: prepare → preflight → generate → remeasure → evaluate. Exact dependencies are in dependencies.lock.yaml; scientific variables/controls/population/limitations are in experiment.yaml. Engine-specific validators and declared output JSON schemas are enforced; smoke execution does not validate scientific quality.
