# e02_no_guidance

Does no-guidance generation change the frozen 48-base / 240-evaluation comparison?

Protocol: `E02_MIN_NG_V0`. Owner: `storygen-rewrite`. Scientific inputs and provider versions are fixed by `dependencies.lock.yaml`. Historical CLIs remain unchanged.

```bash
python experiments/reviewer_round1/e02_no_guidance/e02_no_guidance.py plan
python experiments/reviewer_round1/e02_no_guidance/e02_no_guidance.py preflight --config /absolute/exact_configuration.json --run-id UNIQUE_ID
python experiments/reviewer_round1/e02_no_guidance/e02_no_guidance.py run --config /absolute/exact_configuration.json --run-id UNIQUE_ID
python experiments/reviewer_round1/e02_no_guidance/e02_no_guidance.py status --config /absolute/exact_configuration.json --run-id UNIQUE_ID
```

`plan` lists required bindings. Configuration supplies `purpose` (`RESEARCH` or `MIGRATION_VERIFICATION`), `inputs` with exact `path`/`sha256` file references, and protocol settings listed by the plan. Defaults resolve the eight roots under `~/projects`; explicit `source_roots`/`depot_roots` can bind another workspace. Changed provider source cannot silently replace locked commits; preflight materializes an exact detached checkout in the provider cache if required. Models/servers remain the frozen local profile; no downloads or implicit method substitutions.

Outputs are create-only `storygen-rewrite-depot/experiments/reviewer_round1/e02_no_guidance/runs/UNIQUE_ID/`. One global ID is shared across participating producers. Failed runs stay sealed; use a fresh ID for a justified retry. Never use these verification outputs as primary paper results. All scoring and validation remain in the exact frozen providers.
