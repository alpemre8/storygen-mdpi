# TasksetV5 block

This block owns the frozen TasksetV5 construction that was previously present only in the legacy single-block repository.

It is deterministic and performs **no LLM inference**. It consumes the locked 10-film set plus an existing `storygen.feature-set/1.4` artifact and produces `storygen.taskset-runtime/1.0`.

Canonical design:

- 12 fixed unordered film pairs;
- both directions -> 24 directed pairs;
- two deterministic interval slots per directed pair;
- 16 short, 16 medium, and 16 long base intervals;
- five single-feature tasks per base interval;
- 48 base intervals and 240 tasks total.

The structure hash is locked to the canonical legacy TasksetV5:

`sha256:840aafe93408d41f3ef2e8fe791b0401ce52008060031a58aa46e4e28944bcdb`

Example (external run storage):

```bash
export STORYGEN_FEATURE_DEPOT_ROOT="$HOME/projects/storygen-feature-extraction-depot"
export STORYGEN_REWRITE_DEPOT_ROOT="$HOME/projects/storygen-rewrite-depot"
FEATURE_SET_ID="fs_qwen25_7b_q4km_mc1_1_fev1_4_current_10_films_balanced_v1"
FEATURE_SET_ROOT="$STORYGEN_FEATURE_DEPOT_ROOT/runs/feature_extraction/$FEATURE_SET_ID"

python taskset/cli/build_taskset_runtime.py \
  --film-set "$STORYGEN_FEATURE_DEPOT_ROOT/runs/_inputs/registry/film_sets/current_10_films_balanced_v1.yaml" \
  --input-root "$STORYGEN_FEATURE_DEPOT_ROOT/runs/_inputs" \
  --feature-set-manifest "$FEATURE_SET_ROOT/feature_set_manifest.json" \
  --feature-set-root "$FEATURE_SET_ROOT" \
  --output-root "$STORYGEN_REWRITE_DEPOT_ROOT/runs/tasksets" \
  --overwrite
```
