# E05-4-FEATURE-DIFF

## Research question

When one target feature is modified, how do all five measured features change, especially the four non-target features?

## Historical provenance and population

Frozen TasksetV5: 240 tasks, 48 bases, ten source films, five controlled features, four models × two conditions = 1920 attempted task records and 16000 scene slots. Exact artifact hashes, checkpoint, measurement configuration and repository commits are in input_provenance.json. No new measurement or rewrite was performed.

## Coverage

| model | condition | planned_tasks | available_rewrite_tasks | available_reanalysis_tasks | complete_measurement_tasks | partial_measurement_tasks | missing_tasks | invalid_tasks |
|---|---|---|---|---|---|---|---|---|
| qwen25_7b | DP-v1 | 240 | 239 | 239 | 239 | 0 | 1 | 0 |
| qwen25_7b | CG-v1 | 240 | 235 | 235 | 235 | 0 | 5 | 0 |
| llama31_8b | DP-v1 | 240 | 237 | 237 | 237 | 0 | 3 | 0 |
| llama31_8b | CG-v1 | 240 | 234 | 234 | 234 | 0 | 6 | 0 |
| qwen35_9b | DP-v1 | 240 | 224 | 224 | 224 | 0 | 16 | 0 |
| qwen35_9b | CG-v1 | 240 | 206 | 206 | 206 | 0 | 34 | 0 |
| gemma3_12b | DP-v1 | 240 | 239 | 239 | 239 | 0 | 1 | 0 |
| gemma3_12b | CG-v1 | 240 | 238 | 238 | 238 | 0 | 2 | 0 |

## Metric definitions

Delta = AFTER − BEFORE. Absolute change = abs(delta). Non-target drift = sum of absolute changes over all 4*n non-target scene-feature points divided by 4*n. Complete tasks only. Matrices average within tasks, then across tasks with equal task weights. Direction uses epsilon 1e-12; stored deltas are unchanged. Scores and changes use score units; rates are fractions; matrix percentages use percent.

## Overall feature changes and non-target drift

| model | condition | metric | n_tasks | mean | median | standard_deviation | ci95_low | ci95_high |
|---|---|---|---|---|---|---|---|---|
| qwen25_7b | DP-v1 | mean_absolute_non_target_drift | 239 | 0.092605 | 0.090000 | 0.041111 | 0.085452 | 0.099895 |
| qwen25_7b | DP-v1 | mean_absolute_target_change | 239 | 0.145268 | 0.125000 | 0.093388 | 0.129773 | 0.161964 |
| qwen25_7b | CG-v1 | mean_absolute_non_target_drift | 235 | 0.082960 | 0.077083 | 0.043328 | 0.075741 | 0.090009 |
| qwen25_7b | CG-v1 | mean_absolute_target_change | 235 | 0.135681 | 0.125000 | 0.092206 | 0.119331 | 0.152711 |
| llama31_8b | DP-v1 | mean_absolute_non_target_drift | 237 | 0.145367 | 0.143750 | 0.047020 | 0.135212 | 0.156805 |
| llama31_8b | DP-v1 | mean_absolute_target_change | 237 | 0.181071 | 0.162500 | 0.087998 | 0.165793 | 0.197923 |
| llama31_8b | CG-v1 | mean_absolute_non_target_drift | 234 | 0.117162 | 0.114583 | 0.043690 | 0.109021 | 0.126244 |
| llama31_8b | CG-v1 | mean_absolute_target_change | 234 | 0.153517 | 0.140833 | 0.078794 | 0.141081 | 0.167349 |
| qwen35_9b | DP-v1 | mean_absolute_non_target_drift | 224 | 0.087967 | 0.084375 | 0.038387 | 0.079481 | 0.096931 |
| qwen35_9b | DP-v1 | mean_absolute_target_change | 224 | 0.139773 | 0.118333 | 0.089217 | 0.124547 | 0.156298 |
| qwen35_9b | CG-v1 | mean_absolute_non_target_drift | 206 | 0.085349 | 0.081250 | 0.049598 | 0.075085 | 0.096046 |
| qwen35_9b | CG-v1 | mean_absolute_target_change | 206 | 0.169296 | 0.160000 | 0.110613 | 0.147496 | 0.191077 |
| gemma3_12b | DP-v1 | mean_absolute_non_target_drift | 239 | 0.117256 | 0.112500 | 0.045195 | 0.109492 | 0.125475 |
| gemma3_12b | DP-v1 | mean_absolute_target_change | 239 | 0.202849 | 0.200000 | 0.098445 | 0.186735 | 0.219157 |
| gemma3_12b | CG-v1 | mean_absolute_non_target_drift | 238 | 0.124080 | 0.120833 | 0.043486 | 0.116183 | 0.132431 |
| gemma3_12b | CG-v1 | mean_absolute_target_change | 238 | 0.210000 | 0.200000 | 0.092251 | 0.194385 | 0.226235 |

Largest observed model-condition mean non-target drift: llama31_8b DP-v1 (0.145367). Smallest: qwen25_7b CG-v1 (0.082960).

Largest observed task drift: llama31_8b DP-v1 v5_T0123 = 0.340000.

Smallest observed task drift: qwen25_7b CG-v1 v5_T0022 = 0.003125.

Most frequent non-target increase by equal-task rate: llm_emotion_intensity_score (0.411315; 5001 scene-task occurrences). Reused scenes are not independent.

Most frequent non-target decrease by equal-task rate: llm_action_density_score (0.259196; 3281 scene-task occurrences). Reused scenes are not independent.

## Five-by-five interaction analysis

Rows control one feature; columns measure each feature. Diagonal and off-diagonal cells remain separate. Figure 1 and the mean-absolute matrix are primary; Figure 2 uses a separate signed scale. NA cells are gray. Numeric tables contain all five statistics, explicit task counts and scene coverage for all eight combinations and the global intersection.

Largest off-diagonal mean absolute cell in each model-condition (descriptive):

| model | condition | target_feature | measured_feature | n_tasks | mean |
|---|---|---|---|---|---|
| qwen25_7b | DP-v1 | llm_dialogue_density_score | llm_character_interaction_score | 48 | 0.169826 |
| qwen25_7b | CG-v1 | llm_dialogue_density_score | llm_character_interaction_score | 45 | 0.189519 |
| llama31_8b | DP-v1 | llm_dialogue_density_score | llm_character_interaction_score | 47 | 0.199876 |
| llama31_8b | CG-v1 | llm_dialogue_density_score | llm_character_interaction_score | 46 | 0.160598 |
| qwen35_9b | DP-v1 | llm_character_interaction_score | llm_emotion_intensity_score | 48 | 0.126215 |
| qwen35_9b | CG-v1 | llm_dialogue_density_score | llm_character_interaction_score | 25 | 0.201767 |
| gemma3_12b | DP-v1 | llm_dialogue_density_score | llm_character_interaction_score | 48 | 0.208281 |
| gemma3_12b | CG-v1 | llm_dialogue_density_score | llm_character_interaction_score | 48 | 0.209184 |

Primary absolute interaction heatmaps:

- [Qwen2.5-7B DP-v1](FIGURE_1_qwen25_7b_DP-v1.png)
- [Qwen2.5-7B CG-v1](FIGURE_1_qwen25_7b_CG-v1.png)
- [Llama-3.1-8B DP-v1](FIGURE_1_llama31_8b_DP-v1.png)
- [Llama-3.1-8B CG-v1](FIGURE_1_llama31_8b_CG-v1.png)
- [Qwen3.5-9B DP-v1](FIGURE_1_qwen35_9b_DP-v1.png)
- [Qwen3.5-9B CG-v1](FIGURE_1_qwen35_9b_CG-v1.png)
- [Gemma-3-12B DP-v1](FIGURE_1_gemma3_12b_DP-v1.png)
- [Gemma-3-12B CG-v1](FIGURE_1_gemma3_12b_CG-v1.png)

## DP-v1 versus CG-v1

Paired differences are CG minus DP within identical complete task IDs and intervals.

| model | metric | dp_total_measurable_tasks | cg_total_measurable_tasks | jointly_measurable_tasks | n_tasks | mean | median | ci95_low | ci95_high |
|---|---|---|---|---|---|---|---|---|---|
| qwen25_7b | mean_absolute_non_target_drift | 239 | 235 | 234 | 234 | -0.009492 | -0.010208 | -0.014441 | -0.004859 |
| qwen25_7b | mean_absolute_target_change | 239 | 235 | 234 | 234 | -0.009566 | -0.008333 | -0.016895 | -0.002494 |
| llama31_8b | mean_absolute_non_target_drift | 237 | 234 | 232 | 232 | -0.027778 | -0.027083 | -0.033759 | -0.021594 |
| llama31_8b | mean_absolute_target_change | 237 | 234 | 232 | 232 | -0.027683 | -0.033333 | -0.036571 | -0.017917 |
| qwen35_9b | mean_absolute_non_target_drift | 224 | 206 | 198 | 198 | -0.003991 | -0.003646 | -0.011187 | 0.002823 |
| qwen35_9b | mean_absolute_target_change | 224 | 206 | 198 | 198 | 0.024444 | 0.012500 | 0.012646 | 0.035771 |
| gemma3_12b | mean_absolute_non_target_drift | 239 | 238 | 237 | 237 | 0.006648 | 0.006250 | 0.003072 | 0.010181 |
| gemma3_12b | mean_absolute_target_change | 239 | 238 | 237 | 237 | 0.006431 | 0.008333 | -0.000316 | 0.013561 |

Cell differences are restricted to each task’s controlled-feature row. The CSV includes individual differences and their distribution.

## Four-model comparisons and available-case sensitivity

The actual all-eight complete intersection contains 186 tasks. It is calculated afresh; no historical 186-task set is substituted. Global-common minus available-case means:

| model | condition | metric | available_mean | common_mean | common_minus_available |
|---|---|---|---|---|---|
| qwen25_7b | DP-v1 | mean_absolute_non_target_drift | 0.092605 | 0.090206 | -0.002399 |
| qwen25_7b | DP-v1 | mean_absolute_target_change | 0.145268 | 0.145278 | 0.000009 |
| qwen25_7b | CG-v1 | mean_absolute_non_target_drift | 0.082960 | 0.078623 | -0.004337 |
| qwen25_7b | CG-v1 | mean_absolute_target_change | 0.135681 | 0.133024 | -0.002657 |
| llama31_8b | DP-v1 | mean_absolute_non_target_drift | 0.145367 | 0.144532 | -0.000835 |
| llama31_8b | DP-v1 | mean_absolute_target_change | 0.181071 | 0.181548 | 0.000477 |
| llama31_8b | CG-v1 | mean_absolute_non_target_drift | 0.117162 | 0.117494 | 0.000332 |
| llama31_8b | CG-v1 | mean_absolute_target_change | 0.153517 | 0.156109 | 0.002592 |
| qwen35_9b | DP-v1 | mean_absolute_non_target_drift | 0.087967 | 0.088014 | 0.000047 |
| qwen35_9b | DP-v1 | mean_absolute_target_change | 0.139773 | 0.145287 | 0.005514 |
| qwen35_9b | CG-v1 | mean_absolute_non_target_drift | 0.085349 | 0.084015 | -0.001333 |
| qwen35_9b | CG-v1 | mean_absolute_target_change | 0.169296 | 0.169539 | 0.000242 |
| gemma3_12b | DP-v1 | mean_absolute_non_target_drift | 0.117256 | 0.114954 | -0.002302 |
| gemma3_12b | DP-v1 | mean_absolute_target_change | 0.202849 | 0.202612 | -0.000237 |
| gemma3_12b | CG-v1 | mean_absolute_non_target_drift | 0.124080 | 0.121671 | -0.002409 |
| gemma3_12b | CG-v1 | mean_absolute_target_change | 0.210000 | 0.208557 | -0.001443 |

## Increase/decrease stratification

Historical directions are scene-level INCREASE, DECREASE or MAINTAIN, read from exact archived planner deltas. Heterogeneous tasks are MIXED. Matrices include separate scene-direction strata with within-task denominators; opposite signed changes can cancel while absolute change remains positive. 09_DIRECTION_DISTRIBUTION.csv preserves per-task controlled/measured-feature counts and rates.

## Missingness and exclusions

08_EXCLUSIONS.csv accounts for every omitted task and scene with an explicit reason. Partial tasks contribute diagnostic scene rows but no complete-task metric. Missing values are NA in CSV and null in JSON. Broken hashes/lineage/population/instrument bindings fail preflight rather than becoming historical model failure.

Task exclusions by classification: {"MISSING_REWRITE": 68}.

## Uncertainty and sensitivity

Task SD/quantiles are descriptive. Fixed-seed (250504) base-interval percentile bootstrap uses 2000 replications where at least eight bases are eligible. Paired differences retain matched resampling. See each summary’s CI limitation and eligible-cluster count.

## Methodological limitations

These are changes measured by the canonical Qwen2.5-7B instrument. Feature constructs and human agreement are not independently validated. Qwen2.5 rewrites share a model family/checkpoint with the extractor. Historical clamped measurements cannot recover unclamped predictions.

Feature drift is not content damage, semantic preservation, screenplay quality, or an externally defined violation. High target change does not establish target-guidance success. Correlated narrative properties may move together; no causal independence is established.

DP-v1 and CG-v1 prompts may differ beyond numerical guidance. Their differences are descriptive; E04 is the separate matched-prompt experiment. Previous E05 semantic judge outcomes are not used.

Missingness can select the available-case population. Global matched-common results use the newly calculated complete intersection across eight combinations, not the historical 186-task set. Poor-coverage models remain visible.

Scenes nest within tasks and five tasks share each base. The base-interval cluster bootstrap resamples clusters with all their eligible tasks; within paired comparisons it resamples paired differences, hence the same bases in both conditions. Overlapping bases and film dependence remain. Only ten films exist; no film-cluster sensitivity or independent-scene significance test is reported. Percentile CIs are descriptive and withheld below eight eligible bases.

## Reviewer 1, Comment 6 coverage

The off-diagonal matrices, drift distributions, direction strata and matched comparisons quantify movement of the four non-target measured features. They do not establish semantic preservation or require non-target scores to remain fixed.
