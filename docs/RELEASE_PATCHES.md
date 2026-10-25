# Public packaging patches

## v1.0.1 — portable E05-4 launcher

GitHub's independent Ubuntu runner passed all numerical replays, then exposed a host-specific default in the preserved E05-4 shell launcher: `/home/alp-emre/.venv/bin/python3`. The author's clean local clones still had that interpreter present, so they did not expose this dependence. On GitHub, v1.0.0's test result was 60 passed and one failed (`test_local_cli_safe_help_and_ambiguous_selection`).

The public launcher now defaults to `python3` from the active PATH; the existing `E05_FEATURE_DIFF_PYTHON` override remains supported. Activate the documented venv before running the package. This is a one-line launcher portability patch. Scientific algorithms, prompts, schemas, task populations, decoding settings, recorded observations and statistical outputs are unchanged. The original source SHA and patched public SHA are both recorded in `provenance/SOURCE_MANIFEST.json`.

v1.0.0 remains as a historical tag with its release marked superseded. Use v1.0.1. Historical source/config files can retain machine paths as provenance; full model reruns still require the explicit data/runtime rebinding described in `REPRODUCIBILITY.md`.
