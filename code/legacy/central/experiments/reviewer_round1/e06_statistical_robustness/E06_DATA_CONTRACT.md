# Canonical data and historical bindings

`historical_binding.json` pins exact taskset, original FeatureSet, path override
and eight evaluation/rewriting/reanalysis manifest/ledger identities. It was
assembled from the existing P01B input plan, using metadata only; P01B analysis
results are not E06 input results. `dataset_kind` is mandatory. REAL inputs must
retain the checked-in frozen artifact hashes, exact model order and design
expectations. Path migration is permitted only through explicit hash-checked
bindings/overrides; no fuzzy scanning or silent fallback is used.

Canonical data are one task table plus one index per model-condition pair. Task
keys: task_id, base_interval_id, screenplay_id, reference_screenplay_id, feature,
interval_length, ordered scene_ids/reference_scene_ids, B and T, and original
text reference. Original reference feature values remain available through the
bound original feature rows and reference scene identities; T is the frozen
reference-derived resampled target. The loader reuses the canonical six-decimal
resampling rule where lengths differ and verifies exact transfer-plan values.
No additional rounding is applied during E06 comparisons.

Observation keys extend those with model, condition, eligibility, A, dB, dA, G,
TI, DA, generation_status, measurement_status, failure_classification,
original_status, evaluation_records and scene-aligned text metadata. Text-pair
keys preserve scene_id, scene_position, source_basis, word counts, ratio, status,
was_truncated and exact archive/rewrite/request references. Original text is read
privately and never exported. All source-file SHA-256 values and absences are
recorded in E06_PROVENANCE.json. Implementation hashes are separately retained
in 00_manifest/IMPLEMENTATION_IDENTITY.json.

Duplicate task IDs, unexpected IDs, duplicate scene IDs, nonfinite or out-of-range
features, mismatched model/condition labels and incompatible lineage are errors.
Canonical replay equality compares the complete frozen evaluator record. A
missing ledger entry remains an ineligible planned observation, creates a replay
mismatch, and blocks COMPLETE through V02. It never becomes a successful replay
observation merely because feature files happen to exist. A malformed or changed
artifact fails closed. Missing eligible features cannot be imputed.

Failure mapping preserves original ineligible_reason strings:

| E06 class | Evidence |
|---|---|
| successful_and_measured | Eligible frozen record with exact canonical replay |
| generation_failure | rewrite_failure.json or missing_rewrite_task reason |
| measurement_failure | reanalysis_failure.json or other reanalysis-prefixed reason |
| missing_historical_artifact | Absent ledger entry or remaining missing-artifact reason |
| invalid_or_incompatible_record | Other recorded evaluator ineligibility |

Preflight parses only contracts/identities/metadata and hashes candidate files.
It never replays metrics, parses feature values for calculations or computes
historical eligibility. Source availability is provisional until the human run
verifies alignment. Missing task-local files may be historical failures, not a
reason to delete the planned observation.

For original scripts the frozen Feature IO identity convention is explicit:
integer _id is zero-based and maps to scene_{id+1:03d}; string scene_NNN or numeric
string IDs retain their canonical numeric scene identity. No positional fallback
is allowed for absent source IDs. Requests must match scene, interval, screenplay,
model and prompting strategy; untruncated source text must equal the archive.
Both source bases remain separate if a request records truncation. Missing
requests/unsupported request schemas become unavailable model-presented text.

Generated rewrites with unavailable source/rewrite/request pairs give A06 a
MISSING_INPUT status. Actual generation failures remain in the length ledger
with missing ratios but do not pretend a generated length exists. No valid
length ratios at all also gives MISSING_INPUT. Zero source, empty rewrite and
missing text have distinct statuses. Undefined numerical summaries are null,
never NaN, infinity, a fake zero-distance observation or a successful task.
