# Experiment depot architecture v1

New roots are `experiments/<group>/<experiment>/runs/<global_run_id>/` in each producing depot. The experiment has one source owner; provider repos share its exact run ID and keep their own artifacts. Naturalness is optional and independently owned. The root DEPOT_MANIFEST remains unchanged.

Inputs contain exact configuration and dependency bindings. Raw provider output, tables, reports and stage_receipts are separate from mutable logs. Logs are excluded from scientific artifact hashes; they remain within the exclusively reserved run. RUN_STARTED is create-only; terminal run_manifest and SEALED are create-only. COMPLETE execution does not imply VALIDATED science. Migration verification and synthetic runs cannot be paper results.

RunStore creates exclusively and refuses all subsequent writes when terminal. There is no in-place resume: a failed or interrupted run is retained and a new run ID records parent_run_ids, reusing only explicitly hashed inputs. An interrupted RUN_STARTED without SEALED is incomplete and cannot be resolved as sealed. Individual stage envelopes record failure outputs and stop downstream jobs (execution v4). Seals are integrity checks, not operating-system write protection: unauthorized edits are detected at resolution/indexing.

Artifact refs include producer repo, experiment, protocol, run, role, SHA, schema and a relative locator rooted in a depot ID. `tools/artifacts.py resolve REF.json --require-sealed` checks path containment, no symlinks, producer identity, bytes, seal hash and exact registration. The same basename in two depots never aliases. Indexing produces immutable content-addressed catalog records under catalogs/experiment_architecture_v1/runs.

History stays in place. LEGACY_ARTIFACT_MAP.csv and per-depot legacy.jsonl list exact physical files, SHA and semantic storage roles; they do not upgrade scientific validity. Known historical symlink aliases are preserved and omitted from writable/new reference APIs; consumers bind their physical immutable targets. `legacy` accepts only exact physical locators and hashes. Catalogs are additive; no old run gets new metadata or symlinks.

M00 protects every historical file size/mtime and selected provenance hashes. M08 additionally establishes full-byte SHA baselines for all historical regular files, with symlink target checks; this does not retroactively claim full-byte SHA coverage at M00.
