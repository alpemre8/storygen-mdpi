# e01_independent_extractor

How does the strict independent F16 extractor behave on the locked bounded sample?

Protocol: `E01_INDEPENDENT_FP16_V1`. Owner: `storygen-feature-extraction`. Scientific inputs and provider versions are fixed by `dependencies.lock.yaml`. Historical CLIs remain unchanged.

```bash
python experiments/reviewer_round1/e01_independent_extractor/e01_independent_extractor.py plan
python experiments/reviewer_round1/e01_independent_extractor/e01_independent_extractor.py preflight --config /absolute/exact_configuration.json --run-id UNIQUE_ID
python experiments/reviewer_round1/e01_independent_extractor/e01_independent_extractor.py run --config /absolute/exact_configuration.json --run-id UNIQUE_ID
python experiments/reviewer_round1/e01_independent_extractor/e01_independent_extractor.py status --config /absolute/exact_configuration.json --run-id UNIQUE_ID
```

`plan` lists required bindings. Configuration supplies `purpose` (`RESEARCH` or `MIGRATION_VERIFICATION`), `inputs` with exact `path`/`sha256` file references, and protocol settings listed by the plan. Defaults resolve the eight roots under `~/projects`; explicit `source_roots`/`depot_roots` can bind another workspace. Changed provider source cannot silently replace locked commits; preflight materializes an exact detached checkout in the provider cache if required. Models/servers remain the frozen local profile; no downloads or implicit method substitutions.

Outputs are create-only `storygen-feature-extraction-depot/experiments/reviewer_round1/e01_independent_extractor/runs/UNIQUE_ID/`. One global ID is shared across participating producers. Failed runs stay sealed; use a fresh ID for a justified retry. Never use these verification outputs as primary paper results. All scoring and validation remain in the exact frozen providers.

The frozen default technical checker (`v1`) preserves its historical SHA representation bug and can stop before generation on the known one-trailing-LF server template. Select the verified versioned technical comparator explicitly with `"technical_runtime_version": "v2"` and `"manage_servers": true` in the exact run configuration. It accepts only exact template equality or the originally declared two known hashes plus their verified single-LF relationship. All other edits are rejected. The original scientific scorer, sample, F16 precision, context, prompts, retry/budget rules and results validator remain unchanged. The failed v1 verification stays sealed; the separate v2 verification completed 16 measurements with zero retries/cache hits/failures. These are migration verification results with scientific validity UNVERIFIED.
