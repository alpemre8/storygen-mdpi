# e01_canonical_mistral

Does changing only the canonical measurement model alter existing rewrite measurements?

Protocol: E01_CANONICAL_MISTRAL_F16_MC1_1 / 1.0.0. Scientific validity is UNVERIFIED until qualified separately.

Use `python e01_canonical_mistral.py plan`, then `preflight --config CONFIG --run-id FRESH_ID`, `run`, `status`, `verify`. Outputs belong only to the central experiment depot. Failed/interrupted IDs are retained; resume creates an explicitly linked fresh successor.

Pipeline: remeasure_dp → remeasure_cg. Exact dependencies are in dependencies.lock.yaml; scientific variables/controls/population/limitations are in experiment.yaml. Engine-specific validators and declared output JSON schemas are enforced; smoke execution does not validate scientific quality.
