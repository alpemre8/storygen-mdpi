# Obtain and prepare screenplay inputs locally

The current `main` branch distributes source links and input identities instead of screenplay passages. Public numeric replay needs **no screenplay files**. Original and generated scene prose, rendered requests containing it, E02 `change_summary` fields, and the text-bearing human-rating booklet are not part of this working tree. Forms, rating instructions, numeric observations, experiment definitions, generic prompt templates, and executable schemas remain available.

## 1. Locate the sources

The source corpus is [STAGE](https://github.com/zhuiwen-ai/STAGE), described in [Tian et al. (2026)](https://arxiv.org/abs/2601.08510). The ten film-specific `script.json` links, STAGE movie IDs, exact historical input SHA-256 values, file sizes, and local destinations are in [`sources/sources.json`](../sources/sources.json). These are references to third-party sources, not copies or a grant of rights. Obtain any text yourself under the source's applicable conditions; no repository tool downloads it.

The upstream links are pinned to commit `0234d2ed2a57cf4a7ff5db0f45d77ad68e0dad41`, checked on 27 October 2026. **This is a verified retrieval reference, not a verified historical experiment checkout.** The historical STAGE commit was not recorded in the inspected measurement/input manifests and remains `null`. The local registry calls the imports `legacy_import_v1`; this is a StoryGen import label, not a STAGE release identifier. The checked STAGE catalogue provides no original screenplay-provider URLs, so those fields also remain `null`.

Comparison of the historical files' Git blob identities with the pinned upstream file metadata gives the following result. A mismatch is reported honestly; it is not silently repaired by changing task definitions.

| StoryGen film ID | Historical scenes | STAGE catalogue scenes | Historical bytes match pinned upstream blob |
|---|---:|---:|---|
| `chasing_amy` | 34 | 68 | No |
| `ghostbusters_ii` | 156 | 156 | No |
| `the_private_life_of_sherlock_holmes` | 89 | 89 | No |
| `dog_day_afternoon` | 69 | 138 | No |
| `apocalypse_now` | 60 | 120 | No |
| `drag_me_to_hell` | 75 | 75 | Yes |
| `up_2009` | 181 | 181 | Yes |
| `darkman` | 100 | 100 | Yes |
| `do_the_right_thing` | 98 | 98 | Yes |
| `the_white_ribbon` | 76 | 76 | No |

The available records do not establish a complete upstream-to-historical conversion procedure for the mismatched inputs. Do not guess one by dropping every other scene, truncating, rewriting, or renumbering. Matching titles or scene counts does not establish matching bytes. If you cannot independently obtain a matching historical input, exact original-text reruns for it remain unavailable; you can still reproduce every released numerical analysis, or declare a separate experiment with new inputs.

## 2. Place your own files outside the tracked package

Use the following directory structure in your clone:

```text
local-inputs/
  films/
    chasing_amy/script.json
    ghostbusters_ii/script.json
    the_private_life_of_sherlock_holmes/script.json
    dog_day_afternoon/script.json
    apocalypse_now/script.json
    drag_me_to_hell/script.json
    up_2009/script.json
    darkman/script.json
    do_the_right_thing/script.json
    the_white_ribbon/script.json
```

`local-inputs/` and `external-inputs/` are ignored by Git and excluded from the public inventory/content scan. Put new rendered prompts, generated scene prose, and any locally prepared rating booklet under an ignored local directory as well. Do not force-add these files to Git.

The historical screenplay format is a UTF-8 JSON array in original scene order. Each scene has `_id`, `title`, `subtitle`, and `content` fields. Historical `_id` values are zero-based integers; the retained feature loader maps integer `_id: 0` to `scene_001`, `_id: 1` to `scene_002`, etc. The schema is described here without embedding any scene passage. Preserve the exact original bytes when testing historical input identity; reserializing otherwise equivalent JSON changes its SHA-256.

## 3. Verify file identity without inference

From the repository root:

```bash
python tools/check_source_inputs.py --root local-inputs
```

The checker reads only local files, checks all ten SHA-256 values and scene structures, prints metadata without scene content, and exits successfully only if every input matches. It does not download, convert, modify, or run models. Missing files, changed files, invalid JSON, or a different scene layout cause a nonzero exit. You can point `--root` at another private directory containing the same `films/<film_id>/script.json` layout.

## 4. Connect the verified files to a new experiment

The frozen public taskset is `data/tasksetv5/taskset_runtime.json`; canonical numeric reference features are in `data/original_features/`. Historical absolute paths in these files are provenance. Create **local copies** of the taskset and feature-set manifest under `local-inputs/`, rebind their script and feature paths to your own verified files, and keep the published originals unchanged. Retain task IDs, source/reference scene selections, feature scores, and protocol settings. Use a new run ID and record new manifest hashes for this local binding.

See [`REPRODUCIBILITY.md`](REPRODUCIBILITY.md) for the retained extraction/rewrite CLI entry points, model/server prerequisites, and an example invocation. The ten source scripts alone do not reconstruct every historical generated artifact in the 31,223-file restricted E06 inventory; `tools/check_external_inputs.py` serves that separate full-depot identity check. No automatic full-depot rehydration or exact reconstruction of the omitted rating booklet is claimed.

## Numeric results without any source text

The ordinary `tools/reproduce.py` commands in the README use the released numeric observations only. Input preparation is unnecessary for inspecting recorded results, regenerating the supported paper tables, or running the retained offline tests. See [`provenance/INPUT_TEXT_REMOVAL.json`](../provenance/INPUT_TEXT_REMOVAL.json) for file hashes and the current-branch cleanup record. Existing tags and release archives were not changed by this cleanup.
