# e03_dp48_extension

Extend the frozen DP population to DP48 without regenerating original DP12 or CG observations.

Protocol: `E03_DP48_EXTENSION_V1`. Owner: `storygen-rewrite`. Scientific inputs and provider versions are fixed by `dependencies.lock.yaml`. Historical CLIs remain unchanged.

```bash
python experiments/reviewer_round1/e03_dp48_extension/e03_dp48_extension.py plan
python experiments/reviewer_round1/e03_dp48_extension/e03_dp48_extension.py preflight --config /absolute/exact_configuration.json --run-id UNIQUE_ID
python experiments/reviewer_round1/e03_dp48_extension/e03_dp48_extension.py run --config /absolute/exact_configuration.json --run-id UNIQUE_ID
python experiments/reviewer_round1/e03_dp48_extension/e03_dp48_extension.py status --config /absolute/exact_configuration.json --run-id UNIQUE_ID
```

`plan` lists required bindings. Configuration supplies `purpose` (`RESEARCH` or `MIGRATION_VERIFICATION`), `inputs` with exact `path`/`sha256` file references, and protocol settings listed by the plan. Defaults resolve the eight roots under `~/projects`; explicit `source_roots`/`depot_roots` can bind another workspace. Changed provider source cannot silently replace locked commits; preflight materializes an exact detached checkout in the provider cache if required. Models/servers remain the frozen local profile; no downloads or implicit method substitutions.

Outputs are create-only `storygen-rewrite-depot/experiments/reviewer_round1/e03_dp48_extension/runs/UNIQUE_ID/`. One global ID is shared across participating producers. Failed runs stay sealed; use a fresh ID for a justified retry. Never use these verification outputs as primary paper results. All scoring and validation remain in the exact frozen providers.

This is the DP36 addition to the original DP12 observations, yielding the DP48 comparison. Original CG and DP12 data remain read-only. Historical source references use an explicit source locator: only declared Git revisions with the exact protected SHA may resolve an old checkout path. Scientific artifact hashes still require exact physical file equality. See [the original DP48 protocol](../../../docs/E03_DP48_EXTENSION.md).
