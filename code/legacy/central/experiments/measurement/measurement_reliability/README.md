# measurement_reliability

How repeatable is canonical measurement on the fixed 100-scene study?

Protocol: MEASUREMENT_RELIABILITY_V1 / 1.0.0. Scientific validity is UNVERIFIED until qualified separately.

Use `python measurement_reliability.py plan`, then `preflight --config CONFIG --run-id FRESH_ID`, `run`, `status`, `verify`. Outputs belong only to the central experiment depot. Failed/interrupted IDs are retained; resume creates an explicitly linked fresh successor.

Pipeline: reliability. Exact dependencies are in dependencies.lock.yaml; scientific variables/controls/population/limitations are in experiment.yaml. Engine-specific validators and declared output JSON schemas are enforced; smoke execution does not validate scientific quality.
