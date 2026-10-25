# tasksetv5_main

Execute the frozen TasksetV5 DP/CG reference pipeline with exact cross-repository scientific identities.

Protocol: `TASKSETV5_MAIN_V1`. Owner: `storygen-rewrite`. Scientific inputs and provider versions are fixed by `dependencies.lock.yaml`. Historical CLIs remain unchanged.

```bash
python experiments/tasksetv5/tasksetv5_main/tasksetv5_main.py plan
python experiments/tasksetv5/tasksetv5_main/tasksetv5_main.py preflight --config /absolute/exact_configuration.json --run-id UNIQUE_ID
python experiments/tasksetv5/tasksetv5_main/tasksetv5_main.py run --config /absolute/exact_configuration.json --run-id UNIQUE_ID
python experiments/tasksetv5/tasksetv5_main/tasksetv5_main.py status --config /absolute/exact_configuration.json --run-id UNIQUE_ID
```

`plan` lists required bindings. Configuration supplies `purpose` (`RESEARCH` or `MIGRATION_VERIFICATION`), `inputs` with exact `path`/`sha256` file references, and protocol settings listed by the plan. Defaults resolve the eight roots under `~/projects`; explicit `source_roots`/`depot_roots` can bind another workspace. Changed provider source cannot silently replace locked commits; preflight materializes an exact detached checkout in the provider cache if required. Models/servers remain the frozen local profile; no downloads or implicit method substitutions.

Outputs are create-only `storygen-rewrite-depot/experiments/tasksetv5/tasksetv5_main/runs/UNIQUE_ID/`. One global ID is shared across participating producers. Failed runs stay sealed; use a fresh ID for a justified retry. Never use these verification outputs as primary paper results. All scoring and validation remain in the exact frozen providers.
