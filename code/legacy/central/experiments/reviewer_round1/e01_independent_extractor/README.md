# e01_independent_extractor

How does the strict independent F16 extractor behave on the locked bounded sample?

Protocol: E01_INDEPENDENT_FP16_V1 / 1.0.0. Scientific validity is UNVERIFIED until qualified separately.

Use `python e01_independent_extractor.py plan`, then `preflight --config CONFIG --run-id FRESH_ID`, `run`, `status`, `verify`. Outputs belong only to the central experiment depot. Failed/interrupted IDs are retained; resume creates an explicitly linked fresh successor.

Pipeline: qualify. Exact dependencies are in dependencies.lock.yaml; scientific variables/controls/population/limitations are in experiment.yaml. Engine-specific validators and declared output JSON schemas are enforced; smoke execution does not validate scientific quality.
