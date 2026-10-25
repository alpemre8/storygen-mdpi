# E05-4-FEATURE-DIFF scientific protocol

Protocol **E05_4_FEATURE_DIFF_V1**, version **1.0.0**. Numerical schema/metric
version **1.0.0**. This experiment owns a deterministic analysis, independently
of every previous E05 variant. It imports no historical scientific engine.

## Question and population

When screenplay scenes are rewritten to modify one target narrative feature,
how do all five measured features change, especially the four non-targets?

The primary population is all 240 frozen TasksetV5 tasks for each of four models
(Qwen2.5-7B, Llama-3.1-8B, Qwen3.5-9B, Gemma-3-12B) and both historical conditions
(DP-v1, CG-v1): **1920 planned records**. There are 48 base intervals, five targeted
feature tasks per base, ten source films and 2000 expected scene slots per
combination, totaling **16000 slots**. Missing outcomes stay in this population.
The 186-task historical common set and E05-v3's 20-task selection are not used.

## Instrument, units and identity

Use only the frozen Qwen2.5-7B checkpoint and feature-measurement-v1 / 1.1.0
configuration. The original, rewrite-reference, reanalysis and per-task
measurement attestations must agree. Bindings freeze complete model, instrument,
protocol, prompt, schema, request, decoding and normalization identities.
Historical normalization clamped scores to [0,1]; this analysis never repairs or
clamps them again. Boolean, string, missing, NaN, infinite and out-of-range values
are ineligible. No substitute extractor, Mistral E01 values or new inference.

Canonical feature order:

1. `llm_pacing_score` → pacing.
2. `llm_dialogue_density_score` → dialogue.
3. `llm_action_density_score` → action.
4. `llm_character_interaction_score` → character.
5. `llm_emotion_intensity_score` → emotion.

A scene joins through model, condition, task, base, source film and source scene
ID. The frozen scene list determines one-based interval order, checked separately
from identity. Source `scene_index`, when present on both sides, is film-global.
Repeated source scenes across targeted-feature tasks remain linked to their base;
distinct historical rewrite outcomes are never deduplicated.

The reanalysis input attestation hashes the canonical compact, sorted JSON map of
`rewritten_scenes.json` and `transfer_plan.json` file SHA-256 values. This is the
historical feature-extraction `io.sha256_json` identity format, implemented here
only as a data-lineage check. The manifest also hash-links the rewrite run,
reference feature set and rewrite-time TasksetV5 snapshot. Current and historical
task snapshots must match scientific identity fields despite relocated paths and
historical difficulty metadata differences.

## Four logical stages

**PREPARE** resolves exact frozen inputs, checks hashes/lineage/population, and
constructs all 1920 planned records. It retains numeric measurements and archived
plan/status metadata; consolidated rewrite text is reduced to scene IDs after
hash verification. **VALIDATE** checks task/scene correspondence and measurement
compatibility and produces the coverage/exclusion ledger. **ANALYZE** calculates
numeric differences and aggregates. **REPORT** exports tables, plots, computed
narrative and exact input provenance. Every stage is an owned central local engine;
there is no rewrite, extraction, reanalysis, judge, or semantic audit stage.

## Metrics

For scene i, feature k: `delta(i,k) = after(i,k) - before(i,k)` and
`abs_delta(i,k) = abs(delta(i,k))`, in score units. Original full-precision float
differences are retained in immutable `stages/analyze/raw/analysis.json`.
The fixed **ZERO_EPSILON = 1e-12** classifies outcomes only: increase above epsilon,
decrease below negative epsilon, unchanged otherwise. Stored values are not zeroed.

For a complete task, calculate five mean/median signed changes and five mean/median
absolute changes; scene increase/decrease/unchanged counts and fractions; and
absolute-change >= **0.20** fractions. The 0.20 comparison uses the literal threshold
without an additional tolerance and is a descriptive diagnostic, not success.

For target feature f and n expected scenes:

`NT_DRIFT(t) = sum_i sum_(k != f) abs_delta(i,k) / (4*n)`.

Mean signed target change, mean absolute target change and mean absolute non-target
drift remain separate. No quality composite is defined.

## Interaction matrices and direction

One 5×5 matrix per model-condition; rows are controlled features, columns measured
features. Diagonal cells measure target change; off-diagonal cells non-target change.
First average scenes within each complete task, then average those task means
with equal task weights in the controlled-feature row. Longer intervals do not
receive greater weight. Separate datasets contain mean signed change, mean absolute
change and increase/decrease/unchanged percentages. Each cell retains eligible task
IDs, bases, films, planned/valid/eligible scene counts and metric denominators.
An empty cell is null, never zero. Absolute matrices are primary.

TasksetV5 has no single task-level direction field. Authoritative
`transfer_plan.json` assigns each scene a selected-feature delta and textual directive.
The frozen planner uses exact delta sign: INCREASE, DECREASE or MAINTAIN. This is
separate from the epsilon used for measured outcome directions. An interval with
heterogeneous scene directives is explicitly **MIXED**. Each output keeps this
label and each scene keeps its actual directive. Direction-specific matrices
average eligible scenes within each complete task, then average those task means.
They are not restricted to homogeneous tasks and include explicit stratum counts.
Non-target drift additionally reports both task-direction and scene-direction strata.
Opposite signed changes may cancel; absolute change and direction distributions
must remain visible. Average signed diagonal change is not guidance success.

## Missing data and coverage

A task is COMPLETE only when all expected scenes have all five compatible valid
measurements. PARTIAL tasks retain valid scene diagnostics, but every complete-task
metric is null. Other categories are MISSING_REWRITE, MISSING_REANALYSIS,
MISSING_SCENE_MEASUREMENT, MEASUREMENT_MISMATCH, IDENTITY_MISMATCH,
INVALID_MEASUREMENT, or another explicit failure. Missing before measurements are
invalid; unavailable after observations are missing. Identity corruption, duplicates,
wrong order or wrong instrument cannot become zero change. Every omitted task and
scene receives an explicit ledger reason.

For every combination, planned = complete + partial + missing + invalid tasks;
expected scene slots = valid + missing + invalid pairs. Availability of consolidated
files is distinct from complete measurement eligibility. Historical missing paths
are frozen as missing with no placeholder hash. If a previously missing file
appears, or a bound file disappears/changes, explicit reviewed rebinding is required.
Fundamental population/schema/lineage/instrument failures are **broken bindings**
and abort preparation/preflight; they are never labeled normal model failure.
Per-record historical inconsistencies remain explicit exclusions.

## Comparisons

DP/CG differences are **CG metric minus DP metric** for the identical complete task
ID and source interval. Report each difference, paired n, mean, median, SD, range,
quantiles and eligible clusters. Metrics are absolute non-target drift, absolute
target change, and absolute/signed changes for each matrix cell. A task contributes
only its controlled-feature row; other rows are nonexistent. DP and CG total
measurable task counts and their exact intersection are also reported.

Four-model summaries separate **FULL_AVAILABLE_CASE** from
**GLOBAL_MATCHED_COMMON**. The latter requires the same task to be COMPLETE in all
eight combinations. Its actual intersection is calculated at run time, including
empty intersections. Full and common-set matrices and means are separate, with
membership IDs and available/common mean differences in the report. No model is
removed for poor coverage. Non-target drift is stratified by controlled feature,
measured feature, task/scene target direction, interval length and source film,
with individual-task distributions and large-change fractions.

## Uncertainty and limitations

Primary estimator: equal-weight complete-task mean; report descriptive task SD,
median, minimum/maximum and 2.5/25/75/97.5 percentiles. **2000** deterministic
base-interval cluster-bootstrap draws use NumPy default_rng, fixed seed **250504**,
and sorted eligible base IDs. Resample bases with replacement, keeping all their
eligible tasks and recomputing the task-weighted mean, including unequal cluster
sizes. CIs are 2.5/97.5 percentile limits. For paired effects bootstrap paired
within-task differences, so both conditions use identical resampled bases.
Below eight eligible bases, withhold the CI, report cluster count and reason.
Matrix direction percentages and other cells are descriptive without bootstrap
intervals; uncertainty is supplied for primary model means, drift strata and pairs.

The eight-base minimum is an operational reporting rule, not a guarantee of
statistical reliability. Overlapping bases and film-level dependence remain;
only ten films exist. No film-cluster sensitivity, independent-scene test,
significance claim or universal causal claim is made.

DP and CG prompts can differ beyond numerical guidance; E04 handles the matched-
prompt causal question separately. The study measures the canonical extractor's
scores, not construct validity, human agreement, semantic preservation or quality.
Qwen rewrites share the instrument checkpoint. Non-target movement is not content
damage; no criterion requires all four features to remain fixed. Large target
change need not mean successful guidance, and low drift need not imply quality.
No previous E05 semantic judge results enter this analysis.

## Output and reproducibility

The ten required numbered CSVs, five statistic-specific matrix CSVs, three scientific
Markdown reports, scientific_summary.json, input_provenance.json and artifact_manifest.json
are written only to the central run's `stages/report/raw/`. Nineteen panels are
exported as PNG and PDF: eight absolute matrices, eight signed matrices, drift,
target/non-target comparison and direction distributions. Axes and legends are
consistent; signed/absolute color scales differ, and missing cells are gray/NA.
Installed plotting dependencies are used without installation; an import blocker
preserves tables and is explicitly reported.

CSV columns follow identity fields then alphabetical order; rows use fixed model,
condition, feature and sorted-task traversal. `NA` means missing/undefined, floats
use 17 fixed decimal places, and lists are compact JSON. Counts are integers,
score changes are score units, rates fractions, and percentage matrices percent.
The technical report lists every column and the concise data dictionary. JSON
retains full double precision where fixed CSV formatting rounds tiny values.
Central source/environment locks, artifact hashes, canonical configuration,
population definition, runtime versions, epsilon and bootstrap seed are preserved.
Create-only run IDs and the central immutable seal remain authoritative.

Implementation readiness, input readiness, offline test success, real analysis
completion and scientific validity are distinct states. The implementation task
runs offline tests and bounded read-only binding validation only. The researcher
executes the real full-population run explicitly.
