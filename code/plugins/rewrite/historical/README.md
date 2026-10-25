# StoryGen Rewrite

Standalone owner of Taskset `1.0.0` and Rewrite `1.3.1`. Scientific source,
prompts, generation settings, validation, and task preparation were copied from
`story_generation` without behavioral changes.

```bash
export STORYGEN_REWRITE_DEPOT_ROOT="$HOME/projects/storygen-rewrite-depot"
python taskset/cli/build_taskset_runtime.py --help
python rewrite/cli/run_taskset.py --help
```

Taskset and Rewrite write only beneath `STORYGEN_REWRITE_DEPOT_ROOT` and read
FeatureSets through explicit paths.

## E05 sequential author workflow

The sole public E05 runner is `tools/e05_content_audit.py`. Active scientific
method `E05_SEQUENTIAL_INTERVAL_V1_R3` preserves the frozen ten matched source
intervals and twenty historical DP/CG rewrites. A reruns the unchanged 100 scene
V3 assessments; B1 extracts state from 100 individual scene pairs; B2 audits 80
adjacent boundaries from four validated compact records per call. All 280 primary
requests have at most one technical repair. No calibration or human evaluation.

Use the new preparation's `AUTHOR_COMMANDS.md` for the exact two-terminal
workflow: `preflight`, `check-model`, `server-judge`, `diagnose-template`,
`check-capacity`, `audit`, `analyze`, `evaluate`, `status`. The human operator
starts/stops the persistent four-slot Vulkan Mistral Q4_K_M server and runs all
live tokenizer/inference/evaluation actions. Context stays 16,384 per slot.
Initial live capacity checks cover A/B1. Audit hard-gates actual B2 primary/repair
capacity after sealed B1 and before B2 generation. No truncation, implicit resume
or overwrite. Scientific results remain NOT_RUN until operator execution.

Stage A scene rubrics, complete prompts, focal anchors and six 0–4 dimensions
are unchanged. B1 facts use exact side-specific nonempty focal excerpt anchors,
with deterministic text/offset/hash resolution and self-reported coverage.
B2 can cite only actual validated facts from the two adjacent scene positions;
partial/uncertain extraction requires INDETERMINATE. Technical failure remains
invalid, distinct from scientific uncertainty. Raw first/repair attempts persist.
Progress reports per-stage counts, active/peak, elapsed and observed ETA HH:MM:SS.

T05-A/C keep existing kernels. B and conflict-case D are explicitly versioned
for adjacent scope, preserving their historical tables and all scene/conflict
values. Comparisons use ten paired source intervals; 80 boundaries are nested,
with explicit determinate/indeterminate/invalid denominators and no hypothesis
test. Original DP/CG extraction discrepancies are diagnostics, never merged.

Automated, UNCALIBRATED, exploratory: anchored facts and strict JSON do not
establish semantic truth or complete extraction. Adjacent-only checks cannot
establish long-range/global consistency. Zero positives and all-indeterminate
outcomes remain unchanged and reported. Previous holistic V3/V4 runs and E01–E04
artifacts remain immutable; the old holistic method is not the new method.

R1 binds B1 coverage/UNKNOWN/reasons in mutually exclusive grammar branches and
assigns each side local fact IDs from array order. Strict validators remain;
old outputs are not transformed. The author now authorizes Codex to operate
the E05 server/inference loop only; this supersedes the earlier operator split.

R2 binds B2 status/reason/evidence alternatives to actual validated B1 coverage.
Four model-facing states contain facts and bounded snippets, with immutable
full provenance retained internally. Opaque fact-ID differences are never
scientific content differences. R1 failures stay archived; all280 rerun.

R3 replaces B2 repeated-ID arrays with closed per-record local-ID boolean
selectors. Known IDs resolve exactly; determinate choices require nonempty
selection. Duplicate JSON keys are rejected before decoding. Old failures
are never deduplicated or relabeled; the full experiment runs afresh.
