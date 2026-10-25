# Measurement Core V1.1

Canonical source/reference/after measurement instrument.

V1.1 locks the complete historical Feature Extraction V1 request contract, not only the user prompt and JSON schema:

- system instruction: `Return only valid JSON. No markdown. No explanation.`
- message order: system, then user
- OpenAI-compatible chat-completions endpoint
- JSON-schema response name: `storygen_response`
- temperature `0.0`, max tokens `256`
- the same Qwen2.5-7B Q4_K_M model SHA
- strict measurement and no heuristic fallback

`cli/validate_core.py` verifies legacy request parity, model identity and the llama.cpp server manifest before a measurement run.
