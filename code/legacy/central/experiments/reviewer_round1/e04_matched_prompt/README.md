# e04_matched_prompt

Does numeric guidance change outcomes when every other matched-prompt field is held fixed?

Protocol: E04_MATCHED_PROMPT_V1 / 1.0.0. Scientific validity is UNVERIFIED until qualified separately.

Use `python e04_matched_prompt.py plan`, then `preflight --config CONFIG --run-id FRESH_ID`, `run`, `status`, `verify`. Outputs belong only to the central experiment depot. Failed/interrupted IDs are retained; resume creates an explicitly linked fresh successor.

Pipeline: prepare → preflight → generate_dir → generate_num → validate_generation → remeasure → evaluate. Exact dependencies are in dependencies.lock.yaml; scientific variables/controls/population/limitations are in experiment.yaml. Engine-specific validators and declared output JSON schemas are enforced; smoke execution does not validate scientific quality.
