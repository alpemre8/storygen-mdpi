# e04_matched_prompt

Does numeric guidance change outcomes when every other matched-prompt field is held fixed?

Protocol: `E04_MATCHED_PROMPT_V1`. Owner: `storygen-rewrite`. Scientific inputs and provider versions are fixed by `dependencies.lock.yaml`. Historical CLIs remain unchanged.

```bash
python experiments/reviewer_round1/e04_matched_prompt/e04_matched_prompt.py plan
python experiments/reviewer_round1/e04_matched_prompt/e04_matched_prompt.py preflight --config /absolute/exact_configuration.json --run-id UNIQUE_ID
python experiments/reviewer_round1/e04_matched_prompt/e04_matched_prompt.py run --config /absolute/exact_configuration.json --run-id UNIQUE_ID
python experiments/reviewer_round1/e04_matched_prompt/e04_matched_prompt.py status --config /absolute/exact_configuration.json --run-id UNIQUE_ID
```

`plan` lists required bindings. Configuration supplies `purpose` (`RESEARCH` or `MIGRATION_VERIFICATION`), `inputs` with exact `path`/`sha256` file references, and protocol settings listed by the plan. Defaults resolve the eight roots under `~/projects`; explicit `source_roots`/`depot_roots` can bind another workspace. Changed provider source cannot silently replace locked commits; preflight materializes an exact detached checkout in the provider cache if required. Models/servers remain the frozen local profile; no downloads or implicit method substitutions.

Outputs are create-only `storygen-rewrite-depot/experiments/reviewer_round1/e04_matched_prompt/runs/UNIQUE_ID/`. One global ID is shared across participating producers. Failed runs stay sealed; use a fresh ID for a justified retry. Never use these verification outputs as primary paper results. All scoring and validation remain in the exact frozen providers.

The frozen protocol uses 96 same tasks, two per each of 48 bases, with one MP-DIR/MP-NUM realization and paired seeds. Only current/target/delta fields may differ. All three prompt asset SHA256 values stay fixed; relocated asset addresses receive a new honest provenance-bundle hash with the original hash retained in MIGRATION_BINDING.json. No historical manifest or prompt is edited. See [the historical E04 protocol](../../../docs/E04_MATCHED_PROMPT.md).
