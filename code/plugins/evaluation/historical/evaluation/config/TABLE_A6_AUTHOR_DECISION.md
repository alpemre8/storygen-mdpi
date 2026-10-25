# P01A author decision — 2026-10-10 (Europe/Istanbul)

**APPROVED:** adopt the independently verified NumPy PCG64 bootstrap as the documented scientific analysis protocol for the revised manuscript. Retain the currently published Table A6 values because they have been independently reproduced.

The author explicitly specified `numpy.random.default_rng(42)`, 10,000 resamples, clustering by `base_interval_id` with 48 clusters, 95% percentile intervals with linear interpolation, an independent RNG reset for each model, and preservation of the original paired task populations.

**Historical execution provenance remains UNVERIFIED.** The author explicitly stated: “This approval does not confirm that the recovered legacy script was historically used to generate the manuscript.” This is prospective scientific protocol adoption; it does not establish or rewrite historical execution facts.

Frozen protocol: [table_a6_pcg64_v1.json](table_a6_pcg64_v1.json), SHA-256 `9faa70fab3461aae3b59122eb3b35df43392246a76c48bd2ff37d9471f6ad032`. The protocol binds source implementation commit/file hashes, exact original runtime/reference/evaluation artifact hashes, ordered paired populations and clusters, and the independent verification source/result hashes. Its companion `.sha256` file verifies the exact serialized bytes. Changes require a new protocol revision and an explicit scientific decision.

The existing Evaluation 2.4.1 / contract 2.4 metric formulas, eligibility and populations remain unchanged. The historical MT19937 CLI default and old Paper-22 lock remain available. Revised-manuscript Table A6 uses the explicitly selected approved `numpy-pcg64` procedure. The earlier proposed MT19937 numerical correction was not adopted. The PDF is not edited in P01A.

Record source: direct human author instruction in this chat. Recorded 2026-10-10T00:20:38.928985+03:00.

P01A-only validation and local annotated phase tag `p01a-pass` are authorized once all gates pass. This is a phase assessment tag, not a code/scientific version release. No GitHub push, P01B work or LLM inference is authorized by this decision.
