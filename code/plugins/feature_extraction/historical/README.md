# StoryGen Feature Extraction

Standalone owner of Measurement Core `1.1.0` and Feature Extraction `1.4.1`.
The scientific source was copied from `story_generation` without algorithm,
prompt, schema, model, decoding, or feature-definition changes.

The same Feature Extraction measurement path accepts original screenplay scenes
and rewritten scenes. Rewritten runs are FeatureSets with `source.type` set to
`rewritten`; there is no active Reanalysis package or run namespace.

```bash
export STORYGEN_FEATURE_DEPOT_ROOT="$HOME/projects/storygen-feature-extraction-depot"
python feature_extraction/cli/extract_feature_set.py --help
python feature_extraction/cli/extract_rewritten_feature_set.py --help
```

All CLI output paths must be inside `STORYGEN_FEATURE_DEPOT_ROOT`. Historical
Reanalysis source remains only in the legacy monorepo, and historical artifacts
remain in the frozen common depot plus this block depot's historical namespace.
