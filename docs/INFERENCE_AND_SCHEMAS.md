# Inference settings, executable schemas and truncation

## Measurement response: Appendix B.1 / B.5 clarification

The frozen schema is `code/plugins/feature_extraction/historical/measurement/schemas/narrative_feature_schema_v1.json` (JSON Schema draft 2020-12, SHA-256 `ef9ad464d0840cab9c030eb38728b0543115595dcc061a9d2069b4f7cc0a988c`).

```json
{"features":{"pacing":0.5,"dialogue_density":0.5,"action_density":0.5,"character_interaction":0.5,"emotion_intensity":0.5}}
```

There is exactly one required top-level key, `features`. Its value has exactly the five keys shown above, with finite numeric scores in [0,1]. The schema forbids additional properties at both levels. Therefore “exactly five feature keys” refers to the inner object, not to five top-level keys. `tools/reproduce.py verify` validates the schema, accepts this example and rejects missing, additional, flat and out-of-range examples.

Historical parser behavior must be distinguished from schema validation: `CanonicalFeatureScorer._parse` first parses JSON, then attempts brace-bounded recovery if JSON parsing fails. It requires the nested object and exactly the five inner keys, rejects Boolean/missing/nonfinite scores, converts numeric values to floats, clamps when configured, and rounds to six decimals. The parser itself does not separately reject extra top-level keys; that outer constraint is imposed by the transmitted structured-output schema. The independent FP16 E01 path retains its stricter range rejection. We have not changed either historical behavior to make the appendix appear consistent.

## Prompts and request envelope

- Measurement prompt: `code/plugins/feature_extraction/historical/measurement/prompts/legacy_feature_prompt_v1.txt`, SHA-256 `aede8ce373024f79dbea090cf5d7dbae07edd3b8f7850c683c5affd6c3ad9d24`.
- Canonical config: `.../measurement/configs/feature_measurement_v1.yaml`.
- DP / CG / repair prompts and method configs: `code/plugins/rewrite/historical/rewrite/prompts/` and `configs/methods/`.
- Matched-prompt, no-guidance and repeatability protocols: `code/plugins/rewrite/historical/components/reviewer_protocols/`.
- E01-B prompts and protocols: `code/plugins/e01_b/`; bounded E01 protocols: `code/legacy/central/experiments/reviewer_round1/e01_*/`.

Measurement uses the OpenAI-compatible `/chat/completions` endpoint, system then user messages, and `response_format.type=json_schema`, schema name `storygen_response`. The system message is `Return only valid JSON. No markdown. No explanation.` Original `client.py` implements the request; the executable measurement tests check exact request parity and omitted fields.

## Recorded model and serving identities

`provenance/RECORDED_INFERENCE_MANIFESTS.json` contains selected actual rewrite/measurement manifests, source locations and SHA-256 values. `code/plugins/rewrite/historical/components/tasksetv5/v1/SERVER_PROFILES.json` preserves actual server configurations. Per-experiment `experiment.yaml`, `pipeline.yaml`, method configs and locked native protocol packages define variant-specific settings; they take precedence over a generic summary.

The main benchmark contains Qwen2.5-7B, Llama-3.1-8B, Qwen3.5-9B and Gemma-3-12B rewrite conditions, each with DP-v1 / CG-v1. Canonical measurement is Qwen2.5-7B Q4_K_M. Its recorded checkpoint SHA-256 is `65b8fcd92af6b4fefa935c625d1ac27ea29dcb6ee14589c55a8f115ceaaa1423`; the recorded llama.cpp commit is `1425386fd996511e1f3295e7366c38289a92a271`. Other checkpoint hashes, quantizations and aliases are in the manifests and experiment definitions. E01 FP16 and Q4 measurements remain separate strata.

| Setting | Canonical measurement | Main rewrite |
|---|---|---|
| temperature | 0.0 | 0.2 |
| max_tokens | 256 | 4096 |
| schema retry count | 1 (two maximum attempts) | 1 inline retry as implemented |
| timeout | canonical config 600 s | recorded main runs 900 s |
| concurrency | 8 | recorded 4 or 8; model/run dependent |
| context | minimum 8192 per slot in generic measurement config; main TasksetV5 actual 12288 per slot | actual main profiles 12288 per slot |
| top_p, top_k, min_p, seed, stop, repetition penalty | null / omitted unless a particular protocol records a value | use actual request/profile records; absent values remain unspecified |

The canonical request sends only non-null sampler fields. Null is not evidence of a numeric default or a fixed seed. Historical server defaults that were not recorded are unknown; bit-identical fresh generation is not promised. Server profiles also record parallel slots, total context, batching, microbatching, cache/KV types, flash attention, continuous batching, backend and thread settings. Generic minimum requirements must not be substituted for a run's actual settings.

## Truncation and validation rules

`code/plugins/rewrite/historical/rewrite/src/storygen/services/rewrite_engine.py:_truncate_scene_text` keeps the input unchanged when its character count is at most `max_scene_chars` (default **12000** in the frozen rewrite entry points). Otherwise it takes the first `max(0, limit - len(marker))` characters, strips trailing whitespace and appends:

```text
[TRUNCATED FOR LOCAL CONTEXT WINDOW; preserve visible continuity.]
```

The marker starts with a newline in the implementation. Truncation counts Python string characters, not tokenizer tokens. Per-scene prompts record `was_truncated`. Retry payloads use the original separate invalid-response truncation helpers: the per-scene previous invalid response is bounded at 4000 characters; the older interval repair path uses its own 12000-character helper. These are not source-scene limits. Exact marker/prefix behavior is in the retained functions.

The canonical measurement scorer renders the supplied scene text in full; it does not apply the rewrite scene truncation helper. Server context admission is a separate limit. The release includes recorded word-count/truncation diagnostics in E06 for both full archived and model-presented sources, without distributing their text.

Rewrite parsing, exact scene coverage, JSON repair, plan-like/runaway output rejection and measurement eligibility rules remain in the original code. Invalid/missing observations keep their recorded status and denominator. Canonical TI is strict `after_target_MAE < before_target_MAE`; DA uses exact signs, with maintain requiring exact zero in the canonical metric. E06 tolerance sweeps are diagnostics and do not replace those metrics.
