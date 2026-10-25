# E01-B comparison

TI and DA are fractions (0–1). Gain is Before–Target MAE minus After–Target MAE.
Each row uses its own extractor for Before, Target and After. The table is descriptive; paired contrasts below use only their explicit common eligible task IDs.

The historical FP16 run used context/slot 9216, batch 512, ubatch 128 and 16 GPU layers. New Q4 uses the original Qwen settings: context/slot 12288, batch 16384, ubatch 2048; GPU offloading remains the same binary's default. The FP16/Q4 contrast is descriptive and is not an isolated causal precision effect.

| rewrite_model | condition | extractor | precision | status | TI | DA | mean_gain | measurable_n | attempted_n | nonmeasurable_n | before_target_distance | after_target_distance |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Qwen2.5-7B | DP-v1 | Qwen2.5-7B | Q4_K_M | HISTORICAL | 0.719665 | 0.533543 | 0.047228 | 239 | 240 | 1 | 0.277552 | 0.230324 |
| Qwen2.5-7B | CG-v1 | Qwen2.5-7B | Q4_K_M | HISTORICAL | 0.804255 | 0.532801 | 0.054908 | 235 | 240 | 5 | 0.277862 | 0.222954 |
| Qwen2.5-7B | DP-v1 | Mistral-7B | Q4_K_M | MEASURED | 0.631799 | 0.487099 | 0.032923 | 239 | 240 | 1 | 0.282938 | 0.250015 |
| Qwen2.5-7B | CG-v1 | Mistral-7B | Q4_K_M | MEASURED | 0.646809 | 0.462872 | 0.036494 | 235 | 240 | 5 | 0.283335 | 0.246841 |
| Gemma-3-12B | DP-v1 | Qwen2.5-7B | Q4_K_M | HISTORICAL | 0.878661 | 0.718689 | 0.084362 | 239 | 240 | 1 | 0.278354 | 0.193992 |
| Gemma-3-12B | CG-v1 | Qwen2.5-7B | Q4_K_M | HISTORICAL | 0.932773 | 0.735504 | 0.105413 | 238 | 240 | 2 | 0.278754 | 0.173340 |
| Gemma-3-12B | DP-v1 | Mistral-7B | Q4_K_M | MEASURED | 0.723849 | 0.586471 | 0.053775 | 239 | 240 | 1 | 0.281574 | 0.227799 |
| Gemma-3-12B | CG-v1 | Mistral-7B | Q4_K_M | MEASURED | 0.773109 | 0.610224 | 0.074625 | 238 | 240 | 2 | 0.284280 | 0.209655 |
| Gemma-3-12B | CG-v1 | Mistral-7B | FP16 | HISTORICAL | 0.764706 | 0.617577 | 0.075585 | 238 | 240 | 2 | 0.280872 | 0.205287 |

## Paired comparisons

CI: original E01 base-interval cluster bootstrap, 10,000 resamples, PCG64 seed 42. Each contrast is right minus left; eligibility differences are retained.

### qwen_dp_MQ4_K_M_minus_Q

Matched n=239 / 240; exact task IDs and both extractors' matched means are in comparison.json.

- TI_pp: -8.786610878661088; 95% CI [-16.317991631799163, -1.25]; base-interval clusters
- DA_pp: -4.644351464435147; 95% CI [-8.242687267549975, -0.9478298611111124]; base-interval clusters
- mean_gain: -0.014305439330543936; 95% CI [-0.02382517433751743, -0.0048596971215264404]; base-interval clusters

### qwen_cg_MQ4_K_M_minus_Q

Matched n=235 / 240; exact task IDs and both extractors' matched means are in comparison.json.

- TI_pp: -15.74468085106383; 95% CI [-22.64957264957265, -8.936170212765957]; base-interval clusters
- DA_pp: -6.992907801418441; 95% CI [-9.791711182336181, -4.148934275928958]; base-interval clusters
- mean_gain: -0.018414184397163122; 95% CI [-0.027279924812308967, -0.00927186810330193]; base-interval clusters

### gemma_dp_MQ4_K_M_minus_Q

Matched n=239 / 240; exact task IDs and both extractors' matched means are in comparison.json.

- TI_pp: -15.481171548117155; 95% CI [-21.428571428571427, -9.663865546218487]; base-interval clusters
- DA_pp: -13.221757322175732; 95% CI [-16.094954613644617, -10.433940972222222]; base-interval clusters
- mean_gain: -0.030586820083682006; 95% CI [-0.043418048400453275, -0.017630622384937244]; base-interval clusters

### gemma_cg_MQ4_K_M_minus_Q

Matched n=238 / 240; exact task IDs and both extractors' matched means are in comparison.json.

- TI_pp: -15.966386554621849; 95% CI [-22.26890756302521, -9.663865546218487]; base-interval clusters
- DA_pp: -12.528011204481793; 95% CI [-15.266106442577032, -9.774900941389216]; base-interval clusters
- mean_gain: -0.03078781512605042; 95% CI [-0.04449732741197745, -0.017446614675673128]; base-interval clusters

### gemma_cg_MFP16_minus_Q

Matched n=238 / 240; exact task IDs and both extractors' matched means are in comparison.json.

- TI_pp: -16.80672268907563; 95% CI [-22.594142259414227, -11.016949152542374]; base-interval clusters
- DA_pp: -11.792717086834733; 95% CI [-14.902135854341735, -8.652757352941176]; base-interval clusters
- mean_gain: -0.02982843137254902; 95% CI [-0.042250727981065835, -0.017377179218967934]; base-interval clusters

### gemma_cg_Q4_minus_FP16

Matched n=238 / 240; exact task IDs and both extractors' matched means are in comparison.json.

- TI_pp: 0.8403361344537815; 95% CI [-4.621848739495798, 6.3559322033898304]; base-interval clusters
- DA_pp: -0.7352941176470589; 95% CI [-2.932746010638298, 1.3854744159693153]; base-interval clusters
- mean_gain: -0.0009593837535014025; 95% CI [-0.007514100618880035, 0.005310528447780781]; base-interval clusters

### qwen_Qwen2.5-7B_CG_minus_DP

Matched n=234 / 240; exact task IDs and both extractors' matched means are in comparison.json.

- TI_pp: 8.11965811965812; 95% CI [1.702127659574468, 14.655172413793103]; base-interval clusters
- DA_pp: -0.3881766381766381; 95% CI [-3.208181140230725, 2.4422923285584233]; base-interval clusters
- mean_gain: 0.0069586894586894585; 95% CI [-0.0014416898552306134, 0.015438029661016945]; base-interval clusters

### qwen_Mistral-7B_CG_minus_DP

Matched n=234 / 240; exact task IDs and both extractors' matched means are in comparison.json.

- TI_pp: 1.2820512820512822; 95% CI [-5.932203389830509, 8.370876985155284]; base-interval clusters
- DA_pp: -2.66025641025641; 95% CI [-5.594767720306512, 0.21188694554633936]; base-interval clusters
- mean_gain: 0.0030840455840455837; 95% CI [-0.006680737400626572, 0.013154246676286313]; base-interval clusters

### gemma_Qwen2.5-7B_CG_minus_DP

Matched n=237 / 240; exact task IDs and both extractors' matched means are in comparison.json.

- TI_pp: 5.485232067510548; 95% CI [1.2605042016806722, 9.872308346899496]; base-interval clusters
- DA_pp: 1.59634317862166; 95% CI [-0.3473090277777773, 3.541754943502824]; base-interval clusters
- mean_gain: 0.02095991561181435; 95% CI [0.014624833683473393, 0.027468791020592333]; base-interval clusters

### gemma_Mistral-7B_CG_minus_DP

Matched n=237 / 240; exact task IDs and both extractors' matched means are in comparison.json.

- TI_pp: 5.063291139240507; 95% CI [-0.41841004184100417, 10.41775627615061]; base-interval clusters
- DA_pp: 2.524613220815753; 95% CI [0.2464299841772151, 4.8269956524589395]; base-interval clusters
- mean_gain: 0.020922292545710267; 95% CI [0.013901834081090064, 0.027788864486561236]; base-interval clusters

## Failures

- qwen_dp / Qwen2.5-7B / Q4_K_M: 1 ineligible of 240. Exact reasons are in task_records.json.
- qwen_cg / Qwen2.5-7B / Q4_K_M: 5 ineligible of 240. Exact reasons are in task_records.json.
- gemma_dp / Qwen2.5-7B / Q4_K_M: 1 ineligible of 240. Exact reasons are in task_records.json.
- gemma_cg / Qwen2.5-7B / Q4_K_M: 2 ineligible of 240. Exact reasons are in task_records.json.
- gemma_cg / Mistral-7B / FP16: 2 ineligible of 240. Exact reasons are in task_records.json.
- qwen_dp / Mistral-7B / Q4_K_M: 1 ineligible of 240. Exact reasons are in task_records.json.
- qwen_cg / Mistral-7B / Q4_K_M: 5 ineligible of 240. Exact reasons are in task_records.json.
- gemma_cg / Mistral-7B / Q4_K_M: 2 ineligible of 240. Exact reasons are in task_records.json.
- gemma_dp / Mistral-7B / Q4_K_M: 1 ineligible of 240. Exact reasons are in task_records.json.

## Reviewer analysis (offline)

All statistics use recorded scores. TI/DA contrasts are percentage points; gain and score differences remain on the 0–1 score scale.
Conditional table N and paired matched N are different populations. Exact task IDs, exclusions, cluster identities, method details and score-source hashes are in comparison.json.
Bootstrap: 48 represented base-interval clusters for these runs, 10,000 draws, PCG64 seed42, 95% linear percentile; task-weighted means.

### Paired contrasts and difference of TI drops

| contrast | metric | matched_n | cluster_n | point | ci95_low | ci95_high | ci_reason |
| --- | --- | --- | --- | --- | --- | --- | --- |
| qwen_dp_MQ4_K_M_minus_Q | TI_pp | 239 | 48 | -8.786611 | -16.317992 | -1.250000 | NA |
| qwen_dp_MQ4_K_M_minus_Q | DA_pp | 239 | 48 | -4.644351 | -8.242687 | -0.947830 | NA |
| qwen_dp_MQ4_K_M_minus_Q | mean_gain | 239 | 48 | -0.014305 | -0.023825 | -0.004860 | NA |
| qwen_cg_MQ4_K_M_minus_Q | TI_pp | 235 | 48 | -15.744681 | -22.649573 | -8.936170 | NA |
| qwen_cg_MQ4_K_M_minus_Q | DA_pp | 235 | 48 | -6.992908 | -9.791711 | -4.148934 | NA |
| qwen_cg_MQ4_K_M_minus_Q | mean_gain | 235 | 48 | -0.018414 | -0.027280 | -0.009272 | NA |
| gemma_dp_MQ4_K_M_minus_Q | TI_pp | 239 | 48 | -15.481172 | -21.428571 | -9.663866 | NA |
| gemma_dp_MQ4_K_M_minus_Q | DA_pp | 239 | 48 | -13.221757 | -16.094955 | -10.433941 | NA |
| gemma_dp_MQ4_K_M_minus_Q | mean_gain | 239 | 48 | -0.030587 | -0.043418 | -0.017631 | NA |
| gemma_cg_MQ4_K_M_minus_Q | TI_pp | 238 | 48 | -15.966387 | -22.268908 | -9.663866 | NA |
| gemma_cg_MQ4_K_M_minus_Q | DA_pp | 238 | 48 | -12.528011 | -15.266106 | -9.774901 | NA |
| gemma_cg_MQ4_K_M_minus_Q | mean_gain | 238 | 48 | -0.030788 | -0.044497 | -0.017447 | NA |
| gemma_cg_MFP16_minus_Q | TI_pp | 238 | 48 | -16.806723 | -22.594142 | -11.016949 | NA |
| gemma_cg_MFP16_minus_Q | DA_pp | 238 | 48 | -11.792717 | -14.902136 | -8.652757 | NA |
| gemma_cg_MFP16_minus_Q | mean_gain | 238 | 48 | -0.029828 | -0.042251 | -0.017377 | NA |
| gemma_cg_Q4_minus_FP16 | TI_pp | 238 | 48 | 0.840336 | -4.621849 | 6.355932 | NA |
| gemma_cg_Q4_minus_FP16 | DA_pp | 238 | 48 | -0.735294 | -2.932746 | 1.385474 | NA |
| gemma_cg_Q4_minus_FP16 | mean_gain | 238 | 48 | -0.000959 | -0.007514 | 0.005311 | NA |
| qwen_Qwen2.5-7B_CG_minus_DP | TI_pp | 234 | 48 | 8.119658 | 1.702128 | 14.655172 | NA |
| qwen_Qwen2.5-7B_CG_minus_DP | DA_pp | 234 | 48 | -0.388177 | -3.208181 | 2.442292 | NA |
| qwen_Qwen2.5-7B_CG_minus_DP | mean_gain | 234 | 48 | 0.006959 | -0.001442 | 0.015438 | NA |
| qwen_Mistral-7B_CG_minus_DP | TI_pp | 234 | 48 | 1.282051 | -5.932203 | 8.370877 | NA |
| qwen_Mistral-7B_CG_minus_DP | DA_pp | 234 | 48 | -2.660256 | -5.594768 | 0.211887 | NA |
| qwen_Mistral-7B_CG_minus_DP | mean_gain | 234 | 48 | 0.003084 | -0.006681 | 0.013154 | NA |
| gemma_Qwen2.5-7B_CG_minus_DP | TI_pp | 237 | 48 | 5.485232 | 1.260504 | 9.872308 | NA |
| gemma_Qwen2.5-7B_CG_minus_DP | DA_pp | 237 | 48 | 1.596343 | -0.347309 | 3.541755 | NA |
| gemma_Qwen2.5-7B_CG_minus_DP | mean_gain | 237 | 48 | 0.020960 | 0.014625 | 0.027469 | NA |
| gemma_Mistral-7B_CG_minus_DP | TI_pp | 237 | 48 | 5.063291 | -0.418410 | 10.417756 | NA |
| gemma_Mistral-7B_CG_minus_DP | DA_pp | 237 | 48 | 2.524613 | 0.246430 | 4.826996 | NA |
| gemma_Mistral-7B_CG_minus_DP | mean_gain | 237 | 48 | 0.020922 | 0.013902 | 0.027789 | NA |
| qwen_minus_gemma_TI_drop_DP-v1 | TI_pp | 238 | 48 | -6.722689 | -15.833333 | 2.083333 | NA |
| qwen_minus_gemma_TI_drop_CG-v1 | TI_pp | 233 | 48 | -0.429185 | -8.260870 | 7.327586 | NA |

TI drop difference = (Qwen rewrites: Qwen − Mistral Q4) − (Gemma rewrites: Qwen − Mistral Q4), on the four-cell common task intersection. Positive means a larger drop for Qwen rewrites.

### Mistral mean gain: own confidence intervals

| group | precision | matched_n | cluster_n | point | ci95_low | ci95_high | ci_reason |
| --- | --- | --- | --- | --- | --- | --- | --- |
| gemma_cg | FP16 | 238 | 48 | 0.075585 | 0.061375 | 0.090724 | NA |
| gemma_cg | Q4_K_M | 238 | 48 | 0.074625 | 0.059762 | 0.090510 | NA |
| gemma_dp | Q4_K_M | 239 | 48 | 0.053775 | 0.038803 | 0.068982 | NA |
| qwen_cg | Q4_K_M | 235 | 48 | 0.036494 | 0.024569 | 0.049417 | NA |
| qwen_dp | Q4_K_M | 239 | 48 | 0.032923 | 0.023018 | 0.043307 | NA |

### Task-level TI decision agreement

| group | precision | matched_n | both_pass | both_fail | qwen_only_pass | mistral_only_pass | agreement |
| --- | --- | --- | --- | --- | --- | --- | --- |
| gemma_cg | FP16 | 238 | 170 | 4 | 52 | 12 | 0.731092 |
| gemma_cg | Q4_K_M | 238 | 172 | 4 | 50 | 12 | 0.739496 |
| gemma_dp | Q4_K_M | 239 | 159 | 15 | 51 | 14 | 0.728033 |
| qwen_cg | Q4_K_M | 235 | 133 | 27 | 56 | 19 | 0.680851 |
| qwen_dp | Q4_K_M | 239 | 121 | 37 | 51 | 30 | 0.661088 |

Agreement is a fraction. Historical 73.11% refers to FP16; Q4 is calculated separately.

### Table 11b: per-dimension extractor agreement

| population | phase | group | feature | n_pairs | spearman_rho | icc_2_1 | mean_absolute_difference | spearman_reason | icc_reason |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| original | B1 |  | llm_pacing_score | 400 | 0.530438 | 0.404800 | 0.160250 | NA | NA |
| original | B1 |  | llm_dialogue_density_score | 400 | 0.892619 | 0.877816 | 0.115025 | NA | NA |
| original | B1 |  | llm_action_density_score | 400 | 0.614414 | 0.566828 | 0.177325 | NA | NA |
| original | B1 |  | llm_character_interaction_score | 400 | 0.789536 | 0.798366 | 0.151525 | NA | NA |
| original | B1 |  | llm_emotion_intensity_score | 400 | 0.782756 | 0.748944 | 0.136425 | NA | NA |
| rewritten | B1 | qwen_dp | llm_pacing_score | 1988 | 0.500419 | 0.390006 | 0.156388 | NA | NA |
| rewritten | B1 | qwen_dp | llm_dialogue_density_score | 1988 | 0.866069 | 0.847081 | 0.128979 | NA | NA |
| rewritten | B1 | qwen_dp | llm_action_density_score | 1988 | 0.680430 | 0.633251 | 0.160176 | NA | NA |
| rewritten | B1 | qwen_dp | llm_character_interaction_score | 1988 | 0.733652 | 0.746997 | 0.170382 | NA | NA |
| rewritten | B1 | qwen_dp | llm_emotion_intensity_score | 1988 | 0.770295 | 0.737141 | 0.126293 | NA | NA |
| rewritten | B1 | qwen_cg | llm_pacing_score | 1959 | 0.493809 | 0.395195 | 0.151812 | NA | NA |
| rewritten | B1 | qwen_cg | llm_dialogue_density_score | 1959 | 0.868666 | 0.847268 | 0.132231 | NA | NA |
| rewritten | B1 | qwen_cg | llm_action_density_score | 1959 | 0.680335 | 0.625230 | 0.161368 | NA | NA |
| rewritten | B1 | qwen_cg | llm_character_interaction_score | 1959 | 0.740089 | 0.752275 | 0.167565 | NA | NA |
| rewritten | B1 | qwen_cg | llm_emotion_intensity_score | 1959 | 0.751265 | 0.721141 | 0.131572 | NA | NA |
| original | B2 |  | llm_pacing_score | 400 | 0.518960 | 0.393747 | 0.160750 | NA | NA |
| original | B2 |  | llm_dialogue_density_score | 400 | 0.892803 | 0.878011 | 0.114775 | NA | NA |
| original | B2 |  | llm_action_density_score | 400 | 0.617253 | 0.568618 | 0.175575 | NA | NA |
| original | B2 |  | llm_character_interaction_score | 400 | 0.799107 | 0.808575 | 0.148025 | NA | NA |
| original | B2 |  | llm_emotion_intensity_score | 400 | 0.780754 | 0.746781 | 0.136675 | NA | NA |
| rewritten | B2 | gemma_cg | llm_pacing_score | 1976 | 0.528227 | 0.369472 | 0.162753 | NA | NA |
| rewritten | B2 | gemma_cg | llm_dialogue_density_score | 1976 | 0.851441 | 0.834578 | 0.120481 | NA | NA |
| rewritten | B2 | gemma_cg | llm_action_density_score | 1976 | 0.673420 | 0.625973 | 0.149772 | NA | NA |
| rewritten | B2 | gemma_cg | llm_character_interaction_score | 1976 | 0.773887 | 0.748219 | 0.160622 | NA | NA |
| rewritten | B2 | gemma_cg | llm_emotion_intensity_score | 1976 | 0.780708 | 0.759549 | 0.112854 | NA | NA |
| original | B3 |  | llm_pacing_score | 400 | 0.516176 | 0.392131 | 0.161250 | NA | NA |
| original | B3 |  | llm_dialogue_density_score | 400 | 0.892993 | 0.877836 | 0.115025 | NA | NA |
| original | B3 |  | llm_action_density_score | 400 | 0.614592 | 0.566480 | 0.176075 | NA | NA |
| original | B3 |  | llm_character_interaction_score | 400 | 0.797349 | 0.806472 | 0.149025 | NA | NA |
| original | B3 |  | llm_emotion_intensity_score | 400 | 0.783392 | 0.750084 | 0.135425 | NA | NA |
| rewritten | B3 | gemma_dp | llm_pacing_score | 1988 | 0.519881 | 0.377279 | 0.162072 | NA | NA |
| rewritten | B3 | gemma_dp | llm_dialogue_density_score | 1988 | 0.847164 | 0.832277 | 0.124703 | NA | NA |
| rewritten | B3 | gemma_dp | llm_action_density_score | 1988 | 0.679000 | 0.643791 | 0.144180 | NA | NA |
| rewritten | B3 | gemma_dp | llm_character_interaction_score | 1988 | 0.738981 | 0.735917 | 0.166786 | NA | NA |
| rewritten | B3 | gemma_dp | llm_emotion_intensity_score | 1988 | 0.771871 | 0.757141 | 0.114738 | NA | NA |

### Source-curve and implied target-direction agreement

| phase | feature | base_interval_n | source_curve_valid_n | median_source_curve_spearman | same_target_direction | direction_match_n | direction_point_n | direction_unavailable_n |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| B1 | llm_pacing_score | 48 | 46 | 0.477396 | 0.547500 | 219 | 400 | 0 |
| B1 | llm_dialogue_density_score | 48 | 48 | 0.796522 | 0.762500 | 305 | 400 | 0 |
| B1 | llm_action_density_score | 48 | 48 | 0.628066 | 0.625000 | 250 | 400 | 0 |
| B1 | llm_character_interaction_score | 48 | 48 | 0.679692 | 0.680000 | 272 | 400 | 0 |
| B1 | llm_emotion_intensity_score | 48 | 48 | 0.734092 | 0.732500 | 293 | 400 | 0 |
| B2 | llm_pacing_score | 48 | 46 | 0.500679 | 0.547500 | 219 | 400 | 0 |
| B2 | llm_dialogue_density_score | 48 | 48 | 0.796522 | 0.765000 | 306 | 400 | 0 |
| B2 | llm_action_density_score | 48 | 48 | 0.628066 | 0.615000 | 246 | 400 | 0 |
| B2 | llm_character_interaction_score | 48 | 48 | 0.701910 | 0.692500 | 277 | 400 | 0 |
| B2 | llm_emotion_intensity_score | 48 | 48 | 0.768990 | 0.732500 | 293 | 400 | 0 |
| B3 | llm_pacing_score | 48 | 46 | 0.497487 | 0.547500 | 219 | 400 | 0 |
| B3 | llm_dialogue_density_score | 48 | 48 | 0.815079 | 0.762500 | 305 | 400 | 0 |
| B3 | llm_action_density_score | 48 | 48 | 0.628066 | 0.610000 | 244 | 400 | 0 |
| B3 | llm_character_interaction_score | 48 | 48 | 0.695687 | 0.685000 | 274 | 400 | 0 |
| B3 | llm_emotion_intensity_score | 48 | 48 | 0.778117 | 0.732500 | 293 | 400 | 0 |

Original phases each contain the same scene identities, measured separately; they are not pooled. Rewritten score agreement includes all valid paired scene scores, independently of TI eligibility. Source curves count each base interval once per feature; constant curves have undefined Spearman and are excluded only from the median (IDs and counts in JSON).
Undefined statistics are NA with reasons; negative ICC values are retained. No extractor is treated as ground truth. Historical FP16 runtime differs from Q4; precision contrasts remain descriptive.
