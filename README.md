# StoryGen — MDPI scientific reproducibility package

Version **v1.0.1**, prepared 25 October 2026. Public artifact repository: <https://github.com/alpemre8/storygen-mdpi>.

This release contains the actual retained StoryGen implementations, frozen experimental definitions, original prompt templates and executable schemas, recorded inference settings, shareable numeric observations, manuscript tables, and a CPU-only replay tool. The source was exported from the current `storygen` working tree and numeric artifacts from `storygen-depot`. Historical experiments were run in their original repositories; they were **not run in this public repository**. Per-file source hashes and transformations are recorded in [SOURCE_MANIFEST.json](provenance/SOURCE_MANIFEST.json).

## Reproduce the numeric results

Use Python **3.12**. From a fresh clone:

```bash
git clone --branch v1.0.1 https://github.com/alpemre8/storygen-mdpi.git
cd storygen-mdpi
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-lock.txt
python tools/reproduce.py verify
python tools/reproduce.py reproduce --output reproduced
python -m pytest -q
```

`reproduce` forbids network connections and uses recorded observations only. It writes a new output directory and refuses to overwrite one. It recomputes and checks:

- Manuscript Tables 6–10, including the 186-task global-common population and 100-scene × 5-repeat extractor reliability study.
- All nine E01-B comparison cells: coverage, TI, DA, distances and signed gain.
- E02 summary and confidence intervals; E03 repeatability and DP48 extension; E04 matched-prompt results, using their original 10,000-resample analysis kernels.
- Ten E05-4 feature-difference tables from 16,000 scene slots / 1,920 planned task combinations, with the original 2,000-resample bootstrap and seed.
- Thirty E06 tables from its original A01–A07 analyses, including replay of the TI/DA kernels from numeric before/target/after curves.
- Numeric strongest-gain, median-gain and worst-gain Gemma CG-v1 cases. These are reproducibly selected examples, not an assertion about the manuscript's Figure 3 panel identities.

See [verification evidence](verification/REPRODUCTION_REPORT.json), [data dictionary](docs/DATA.md), and [reproduction limits](docs/REPRODUCIBILITY.md). Original tables remain under `data/`; recomputed outputs go to your chosen directory. Numerical comparisons use `rtol=1e-10`, `atol=1e-12`; printed manuscript percentages are checked at their recorded precision.

## Included experiments

The public experiment catalog is exactly the following 14 definitions:

| Family | Experiment IDs | Released numerical material |
|---|---|---|
| Original extraction | `original_feature_extraction` | Canonical feature scores for the ten-film dataset; manifests |
| Reliability | `measurement_reliability` | All 500 recorded repeat measurements and derived statistics |
| Main benchmark | `tasksetv5_main` | Frozen 240-task design, eight model/condition ledgers, Tables 6–10 |
| E01 | `e01_canonical_mistral`, `e01_independent_extractor` | Recorded canonical measurements, bounded independent protocol and its recorded pending status |
| E01-B | `e01_b1_cross_model_precision`, `e01_b2_cross_model_precision`, `e01_b3_cross_model_precision` | Existing completed comparison report and task records; historical FP16 cell remains distinct |
| E02 | `e02_no_guidance` | NG task records, summaries, contrasts and uncertainty |
| E03 | `e03_repeatability`, `e03_dp48_extension` | Original and extension observations, per-repeat and stability analyses |
| E04 | `e04_matched_prompt` | Matched DIR/NUM task records and comparisons |
| E05-4 | `e05_4_feature_diff` | Five-feature before/after measurements, drift and interaction tables |
| E06 | `e06_statistical_robustness` | Numeric diagnostic dataset and A01–A07 tables |

The original `reviewer_analysis` method implementation and selected numeric results are also included. **All other E05 experiments, all E07 experiments, and all GSRN experiments are excluded.** The machine-readable scope is [release-scope.json](release-scope.json). Shared framework source may retain historical references to excluded families; their experiment directories, dedicated implementations and data are omitted.

## Inspect or rerun the original code

```bash
python code/bin/storygen --root code list
python code/bin/storygen --root code graph e05_4_feature_diff --details
python code/plugins/rewrite/historical/rewrite/cli/run_taskset.py --help
```

The `code/` tree preserves the consolidated implementation and the original scientific kernels nested under `historical/` and `legacy/`. Recorded `READY` flags describe the author's local definitions, not the availability of restricted inputs in this public clone. Full model reruns require lawfully obtained screenplay JSON, compatible model weights, a verified llama.cpp server, and rehydration of the frozen inputs. [Rerun instructions](docs/REPRODUCIBILITY.md) distinguish public numeric replay from full generation; neither model weights nor screenplay text are distributed here.

## Response contract and inference settings

The actual measurement response is **one outer `features` object containing exactly five numeric keys**. The executable schema, original parser behavior, truncation rules, retries and omitted sampler parameters are documented in [INFERENCE_AND_SCHEMAS.md](docs/INFERENCE_AND_SCHEMAS.md). Original scientific prompts and configurations are included unchanged. Missing historical settings are explicitly unknown; no sampler or seed is invented.

## Human evaluation materials

The separately supplied [human evaluation package](human-evaluation/) contains the rater forms, short guide, blinded English task booklet and researcher key, with PDF, Word and Excel files available directly. These documents were added after the v1.0.1 scientific release and retain their original filenames and contents.

## Citation, rights and archive status

Use [CITATION.cff](CITATION.cff) to cite this version. [RIGHTS.md](RIGHTS.md) explains the v1.0.1 source and data boundaries. The existing private repositories and the local-only depot are unchanged. The v1.0.1 scientific release excludes screenplay text, generated screenplay passages, model weights and private Git history; the subsequently supplied human evaluation documents are available separately above.

**Zenodo archive/DOI: not created.** The GitHub tag and release version identify this artifact; a DOI must not be claimed until an actual archival record exists. The [Reviewer 1 Comment 8 evidence report](docs/REVIEWER_1_COMMENT_8.md) records completed checks and the remaining manuscript/archive work.
