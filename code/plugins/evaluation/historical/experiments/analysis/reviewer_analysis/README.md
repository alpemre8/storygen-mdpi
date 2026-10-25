# reviewer_analysis

Recompute deterministic A01–A10 reviewer analyses on immutable frozen inputs.

Protocol: `REVIEWER_ANALYSES_P01B_V1`. Owner: `storygen-evaluation`. Scientific inputs and provider versions are fixed by `dependencies.lock.yaml`. Historical CLIs remain unchanged.

```bash
python experiments/analysis/reviewer_analysis/reviewer_analysis.py plan
python experiments/analysis/reviewer_analysis/reviewer_analysis.py preflight --config /absolute/exact_configuration.json --run-id UNIQUE_ID
python experiments/analysis/reviewer_analysis/reviewer_analysis.py run --config /absolute/exact_configuration.json --run-id UNIQUE_ID
python experiments/analysis/reviewer_analysis/reviewer_analysis.py status --config /absolute/exact_configuration.json --run-id UNIQUE_ID
```

`plan` lists required bindings. Configuration supplies `purpose` (`RESEARCH` or `MIGRATION_VERIFICATION`), `inputs` with exact `path`/`sha256` file references, and protocol settings listed by the plan. Defaults resolve the eight roots under `~/projects`; explicit `source_roots`/`depot_roots` can bind another workspace. Changed provider source cannot silently replace locked commits; preflight materializes an exact detached checkout in the provider cache if required. Models/servers remain the frozen local profile; no downloads or implicit method substitutions.

Outputs are create-only `storygen-evaluation-depot/experiments/analysis/reviewer_analysis/runs/UNIQUE_ID/`. One global ID is shared across participating producers. Failed runs stay sealed; use a fresh ID for a justified retry. Never use these verification outputs as primary paper results. All scoring and validation remain in the exact frozen providers.
