# original_feature_extraction

Measure original screenplay scenes with the frozen canonical instrument.

Protocol: FEATURE_MEASUREMENT_V1 / 1.0.0. Scientific validity is UNVERIFIED until qualified separately.

Use `python original_feature_extraction.py plan`, then `preflight --config CONFIG --run-id FRESH_ID`, `run`, `status`, `verify`. Outputs belong only to the central experiment depot. Failed/interrupted IDs are retained; resume creates an explicitly linked fresh successor.

Pipeline: measure. Exact dependencies are in dependencies.lock.yaml; scientific variables/controls/population/limitations are in experiment.yaml. Engine-specific validators and declared output JSON schemas are enforced; smoke execution does not validate scientific quality.

Full population preparation (938 original scenes): [readiness](../../../docs/ORIGINAL_FEATURE_EXTRACTION_READINESS.md).
`research.profile.json` is compiled by `tools/prepare_full_research.py`; it is not a
direct native CLI configuration. Machine-independent execution is **BLOCKED**;
see [operator commands](../../../docs/OPERATOR_COMMANDS.md).
