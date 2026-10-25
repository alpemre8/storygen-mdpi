# Metric definitions and denominators

For task j and its L aligned scenes, B is the original feature curve, T the
reference-derived target and A the re-extracted rewrite curve, all in the
original Qwen [0,1] space. Reuse `storygen_evaluation.metrics.evaluate_task`, `mae`,
`directional_accuracy` and `signum` directly from the pinned evaluation owner.

- dB = sum(|B-T|)/L; dA = sum(|A-T|)/L; signed gain G = dB-dA.
- Canonical TI = 1[dA < dB]. Equal distance is not improvement.
- Canonical DA = sum(1[sign(A-B) = sign(T-B)])/L.
- Conditional TI/DA: arithmetic mean over compatible measured tasks.
- All-attempt TI/DA: sum of valid task contributions / planned task count.
  Every unsuccessful planned observation contributes zero; distances stay null.
- A01 DA_tau changes only desired MAINTAIN hits to 1[abs(A-B) <= tau].
  No floating-point slack is added to these threshold comparisons. At tau=0
  it must equal canonical DA exactly per task and in the results table.
- A01 class contribution: (1/N) sum_j (1/L_j) sum_{k in class} hit_jk.
  Class contributions sum to task-macro DA. Llama CG-minus-DP contributions
  use the same within-model paired task IDs and sum to the paired DA gap.
  The separate scene_accuracy fields are descriptive class hit proportions.
- A02 policy DA: mean_j (number of matching requested directions / L_j).
  Target direction proportions separately pool scene positions. No TI exists.
- A04 exclusion uses actual all-eight-condition eligibility. Scene direction
  distributions count reused positions, not independent screenplay samples.
- A05 feature summaries use actual feature task counts. Their weighted
  all-attempt DA aggregate must reproduce A03. Paired contrasts preserve IDs.
- A06 word count: NFC Unicode normalization, then Python str.split() with no
  argument. Tokens are nonempty Unicode-whitespace-delimited strings; punctuation
  is not removed. Primary task ratio = sum(rewrite_words)/sum(archive_words).
  Model-presented ratios use their own separate source denominator. Macro-average
  task ratios, not scene ratios. No division by zero or partial-task ratios.
  Shortened means ratio<1; lengthened means ratio>1; equal ratios are neither.
- A07 TI_epsilon = 1[G>epsilon], strictly, without pre-rounding. Small-positive
  count = number of eligible tasks with 0<G<=epsilon. At epsilon=0 both per-task
  and aggregate TI must equal canonical TI. Failed tasks stay zero all-attempt.

Percentage-point changes multiply differences of [0,1] metrics by 100. Numeric
CSV/JSON retain calculation precision; report tables format six decimals.
Distribution quantiles use linear interpolation at p*(n-1). Standard deviation
is the sample SD (ddof=1), null for fewer than two observations. Mean/median and
quantiles are null for no observations. Length summaries label each source
basis, model, condition and length. No uncertainty, significance or perceptual
claims follow from these descriptive quantities.

Llama A01 additionally reports condition-conditional and global-common direction
contributions, each with its own explicit DP/CG task denominators, alongside
the within-model paired population. No population is silently substituted.
