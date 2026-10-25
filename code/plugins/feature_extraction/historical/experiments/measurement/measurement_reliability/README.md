# measurement_reliability

How repeatable is canonical measurement on the fixed 100-scene study?

Protocol: `MEASUREMENT_RELIABILITY_V1`. Owner: `storygen-feature-extraction`. Scientific inputs and provider versions are fixed by `dependencies.lock.yaml`. Historical CLIs remain unchanged.

```bash
python experiments/measurement/measurement_reliability/measurement_reliability.py plan
python experiments/measurement/measurement_reliability/measurement_reliability.py preflight --config /absolute/exact_configuration.json --run-id UNIQUE_ID
python experiments/measurement/measurement_reliability/measurement_reliability.py run --config /absolute/exact_configuration.json --run-id UNIQUE_ID
python experiments/measurement/measurement_reliability/measurement_reliability.py status --config /absolute/exact_configuration.json --run-id UNIQUE_ID
```

`plan` lists required bindings. Configuration supplies `purpose` (`RESEARCH` or `MIGRATION_VERIFICATION`), `inputs` with exact `path`/`sha256` file references, and protocol settings listed by the plan. Defaults resolve the eight roots under `~/projects`; explicit `source_roots`/`depot_roots` can bind another workspace. Changed provider source cannot silently replace locked commits; preflight materializes an exact detached checkout in the provider cache if required. Models/servers remain the frozen local profile; no downloads or implicit method substitutions.

Outputs are create-only `storygen-feature-extraction-depot/experiments/measurement/measurement_reliability/runs/UNIQUE_ID/`. One global ID is shared across participating producers. Failed runs stay sealed; use a fresh ID for a justified retry. Never use these verification outputs as primary paper results. All scoring and validation remain in the exact frozen providers.
