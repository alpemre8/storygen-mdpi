# tasksetv5_main

Full population preparation (240 tasks per condition): [readiness](../../../docs/TASKSETV5_READINESS.md).
`research.dp.profile.json` and `research.cg.profile.json` are compiled by
`tools/prepare_full_research.py`; they are not direct native CLI configurations.
Machine-independent execution is **BLOCKED**; see [operator commands](../../../docs/OPERATOR_COMMANDS.md).

How do frozen DP/CG per-scene rewrites move selected narrative features toward their targets?

Protocol: TASKSETV5_MAIN_V1 / 1.0.0. Scientific validity is UNVERIFIED until qualified separately.

Use `python tasksetv5_main.py plan`, then `preflight --config CONFIG --run-id FRESH_ID`, `run`, `status`, `verify`. Outputs belong only to the central experiment depot. Failed/interrupted IDs are retained; resume creates an explicitly linked fresh successor.

Pipeline: build_taskset → bind_runtime → rewrite → remeasure → evaluate. Exact dependencies are in dependencies.lock.yaml; scientific variables/controls/population/limitations are in experiment.yaml. Engine-specific validators and declared output JSON schemas are enforced; smoke execution does not validate scientific quality.
