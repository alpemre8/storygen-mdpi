# Feature Extraction V1.4

This block performs source/reference feature extraction and measurement reliability only.

V1.4 hardening:

- depends on Measurement Core V1.1 and its exact historical request payload
- strict existing-feature-store attestation; it no longer labels arbitrary files as canonical
- validates legacy manifests, model/decoding identity, script hashes, scene IDs/order and all five finite [0,1] scores
- writes `attestation_report.json` and a verified `storygen.feature-set/1.4` manifest
- includes `build_reliability_sample.py` for the canonical 10 films x 10 scenes sample
- reliability requires 100 unique scenes, exactly 10 per film, and five repeats unless explicitly run in noncanonical test mode

## Run-directory contract

Canonical output root is the explicitly supplied external `<runs-root>/01-feature_extraction/`. A feature-set directory is written directly below that root and its ID must carry the relevant version token (for this block, `fev1_4`). Do not create a version-only wrapper such as `feature_sets_v1_4/` for new canonical runs. This is a storage-layout change only; Feature Extraction V1.4's scientific contract is unchanged.


## External runtime storage (V1.4.1)

Feature Extraction no longer owns TasksetV5 binding. Supply explicit `--input-root` and `--output-root` paths. For the current repository layout, use `--input-root "$RUNS_ROOT/_inputs"` and `--output-root "$RUNS_ROOT/01-feature_extraction"`. Taskset construction/binding is owned by `taskset`.
