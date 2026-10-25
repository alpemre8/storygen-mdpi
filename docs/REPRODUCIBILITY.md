# Reproduction levels and full reruns

## Public, CPU-only replay

The README commands are self-contained after installing the pinned Python dependencies. They do not read the author's original repositories, load model weights, call an inference endpoint or require a GPU. Numeric inputs were extracted using the existing E06 loader and its original lineage and SHA checks. That export checked 31,223 input files, found no canonical replay mismatches, and preserved original inputs. The export receipt is `provenance/E06_EXPORT_VALIDATION.json`.

The release replay invokes the retained scientific kernels for E02/E03/E04/E05/E06 and checks the results against separate recorded artifacts. Paper table reconstruction and E01-B summaries are release-level adapters checked against the recorded original tables. The reliability kernel's ICC definition is reused; the remaining reliability formulas follow the original implementation. E01-B's archived reviewer confidence intervals and agreement tables are supplied; the default replay checks its nine coverage/point-estimate cells, not every reviewer agreement/CI calculation.

E06 compares every table's numeric values and labels after omitting private input-file reference columns. Word-count/length-ratio statistics can be recomputed from the released counts, but those counts cannot be independently checked against the withheld text using the public package alone. All original result tables are separate from recomputed outputs. The pinned CPU replay is deterministic; fresh language-model generation need not be bit-identical.

## Full extraction, generation and measurement

Full model reruns require external inputs that are deliberately not redistributed:

1. Lawfully obtained original screenplay JSON with the historical scene segmentation and identifiers, or a clearly declared new dataset. The same film title alone does not establish identical bytes/segmentation. Required historical file hashes are in the manifests.
2. Model checkpoint files with the recorded SHA-256 and quantization, and the recorded llama.cpp revision/backend or a documented new runtime. Models have their own distribution terms and hardware requirements.
3. A verified server manifest matching the selected role and protocol, plus the frozen taskset/reference feature artifacts. Configure your own input/output/model paths and local endpoint; do not substitute the author's absolute paths as executable dependencies.
4. For the exact consolidated orchestration route, rehydrate the relevant depot layout and original immutable input bindings. `tools/check_external_inputs.py --root /path/to/rehydrated/storygen-depot` checks the historical E06 input manifest. Passing this check establishes file identity only, not model availability or scientific qualification of a new run.

The retained original component CLIs expose the actual parameters without depending on an installed global `storygen` executable. These commands only display help:

```bash
python code/plugins/feature_extraction/historical/feature_extraction/cli/extract_feature_set.py --help
python code/plugins/feature_extraction/historical/feature_extraction/cli/extract_rewritten_feature_set.py --help
python code/plugins/rewrite/historical/rewrite/cli/run_taskset.py --help
python code/bin/storygen --root code graph tasksetv5_main
python code/bin/storygen --root code graph e01_b1_cross_model_precision --details
```

For a main benchmark rewrite, after supplying licensed script data and verified local models/server, the original CLI accepts the following form (all uppercase tokens are your explicit values):

```bash
python code/plugins/rewrite/historical/rewrite/cli/run_taskset.py \
  --taskset /your/rehydrated/taskset_runtime.json \
  --feature-set-manifest /your/rehydrated/feature_set_manifest.json \
  --run-id YOUR_NEW_RUN_ID --model RECORDED_MODEL_ALIAS \
  --model-file /your/model.gguf --quantization RECORDED_QUANTIZATION \
  --server-manifest /your/verified_server_manifest.json \
  --strategy CG-v1 --output-root /your/new_outputs \
  --base-url http://127.0.0.1:8080/v1 --temperature 0.2 \
  --rewrite-max-tokens 4096 --schema-retry-count 1 \
  --rewrite-concurrency RECORDED_CONCURRENCY --rewrite-timeout-seconds 900
```

The taskset's script/feature references must resolve to your explicitly verified inputs before running. Original absolute paths and hash-bound manifests cannot all be made relocatable by a search-and-replace without changing provenance. Keep original manifests intact, use documented path mappings, and assign new run IDs to any rebinding. Use the original protocol-specific runners under `code/legacy/central/experiments/` and `code/plugins/*/historical/experiments/` for E01–E04; the E01-B operator guide is included under `code/docs/`. Gates, fixed populations, protocols and immutable input checks are preserved.

No full GPU/model rerun was performed for this release. The complete original private depot is not public. Therefore the validated claim is **public numeric result reproducibility plus inspectable rerun implementations/settings, with restricted-data limits**. It is not unrestricted end-to-end generation reproducibility. No Zenodo DOI is available. The manuscript itself was not edited as part of preparing this repository.
