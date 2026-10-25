# E06 experiment design

Protocol E06_V1, version 1.0.0. Retrospective descriptive analysis of immutable
TasksetV5 and original Qwen measurement-space outputs. The design expectation is
10 screenplays, 48 base intervals, five features, 240 tasks, four rewrite models,
two historical prompting packages, and 1920 planned observations. Reference
expectations (1852 measured, 68 missing observations, 186 common task IDs and
54 excluded unique tasks) are assertions to validate, never substituted for
computed results. The source binding fixes eight exact historical ledgers.

Stages: P00 inventory/preflight; P01 canonical data loading; P02 exact evaluator
replay; P03 seven modules; P04 V01–V15 validation; P05 persisted-result tables
and report; P06 create-only packaging and implementation handoff. An experiment
run is COMPLETE only when every module is complete and every scientific invariant
passes. Scientific validity remains unverified pending independent review.

A01 uses tolerances 0, .025, .050, .100 only for desired MAINTAIN positions.
Desired increase/decrease retain strict sign equality. A dedicated Llama paired
analysis weights class contributions by each task's scene count and then by task
count. It reports exactly which task population was used; its contrast does not
silently inherit a different population from a historical paper table.

A02 predicts ALWAYS_INCREASE, ALWAYS_DECREASE and ALWAYS_MAINTAIN directions.
It uses all frozen definitions, including tasks with failed generations. It is
not a generator, random baseline or TI comparator. Direction proportions are
scene-pooled; policy DA is task-macro. Historical conditional and all-attempt
model DA estimates are included as explicitly labeled comparisons.

A03 preserves the complete model-condition-task grid. Failed/missing/incompatible
observations contribute zero DA/TI in the all-attempt denominator. Distances are
never imputed. A04 independently derives the global-common intersection and
separates excluded unique tasks from missing observations. MIXED tasks retain
scene labels, with separate feature, length and screenplay composition tables.

A05 produces all 40 model-condition-feature groups, conditional and all-attempt
TI/DA, distance summaries, matrices and descriptive paired DP/CG contrasts.
A06 computes task ratios of total word counts followed by macro averaging, plus
separate scene-position distributions and matched DP/CG comparisons. Primary
basis is full archived source; model-presented source is a separate diagnostic.
A07 uses strict signed-gain thresholds 0, .001, .010, .025, .050 on unrounded
floats; it never changes canonical TI or assigns thresholds perceptual meaning.

All summaries and paired differences are descriptive. This version deliberately
reports no confidence intervals or hypothesis tests, so no bootstrap RNG or seed
is invoked. If uncertainty is added in a separately reviewed protocol, reuse the
existing base-interval cluster bootstrap (historical PCG64 10000 resamples, seed
42), preserve pairing, and avoid treating scenes or five features as independent
intervals. A08 is excluded. No inference or semantic judgment is introduced.

Llama A01 additionally reports condition-conditional and global-common direction
contributions, each with its own explicit DP/CG task denominators, alongside
the within-model paired population. No population is silently substituted.
