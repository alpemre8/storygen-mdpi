# Reviewer 1 — Comment 8: release evidence

Prepared 25 October 2026 for version v1.0.1.

- Repository: <https://github.com/alpemre8/storygen-mdpi>
- Versioned release: <https://github.com/alpemre8/storygen-mdpi/releases/tag/v1.0.1>
- Artifact scope: the 14 definitions enumerated in `release-scope.json`, E01–E04, E05-4 feature-diff, E06, original extraction, reliability and the main benchmark, plus the retained reviewer analysis method. Other E05, E07 and GSRN experiments are excluded by the author's requested scope.

The release includes the actual scientific code snapshots, protocols and locked definitions, original prompts, executable JSON schemas, per-run inference metadata and serving profiles, explicit truncation/validation documentation, numeric observations, recorded results and a CPU replay command. `verification/REPRODUCTION_REPORT.json` records the comparisons that actually passed. Checksums and source SHA-256 values make the exact exported artifact inspectable without claiming it produced the historical experiments.

Appendix B can be clarified as follows: “The response has one top-level `features` property whose value contains exactly five required numeric feature keys. The released executable schema prohibits additional properties at both levels.” The historical parser's recovery/coercion/clamping behavior is documented separately; it was not silently replaced with a stricter parser.

The replay also selects strongest-gain, median-gain and worst-gain numeric examples from eligible Gemma CG-v1 tasks. These support balanced inspection, but neither copyrighted scene excerpts nor new manuscript panels are supplied. Matching these examples to Figure 3, editing the appendix/discussion, and shortening repeated discussion text remain manuscript tasks outside this repository request.

## Completed validation and limitations

The original E06 loader verified 31,223 private input files and all 1,920 planned model/condition records, with no canonical replay mismatches. Public replay regenerates Tables 6–10; E01-B's nine point-estimate cells; E02/E03/E04 summaries and uncertainty; the ten E05-4 tables; and thirty E06 tables. The original source's selected measurement/numerical tests and a fresh-clone, isolated Python environment are checked separately; see `verification/VALIDATION.md` for actual outcomes.

No new model inference or GPU run was performed. The bounded independent E01 preparation retains its original NOT_EXECUTED status. Restricted screenplay/derived prose and model weights are not redistributed. Numeric word-count diagnostics cannot be independently validated against omitted text. Original source snapshots retain historical path/hash references; exact full generation requires licensed data and explicit rehydration. No new blanket source/data reuse license has been asserted.

**Zenodo archive/DOI: NOT CREATED.** No DOI is claimed, and no Zenodo deposition was attempted in this repository-only task. A future archive must refer to this exact tag/artifact, with a verified real DOI added to the citation and manuscript.

## Suggested Data Availability Statement

“The code, experimental protocols, original prompt templates, executable response schemas, recorded inference configurations, shareable numerical observations and analysis scripts are available in the versioned StoryGen reproducibility repository (v1.0.1): https://github.com/alpemre8/storygen-mdpi/releases/tag/v1.0.1. Published numerical tables can be regenerated from the released observations. Original screenplay texts, generated screenplay passages and model weights are not redistributed because their distribution rights and licenses are separate. Full generation reruns require independently obtained licensed inputs and the documented hardware/software configuration. No Zenodo DOI is available at the time of this release.”

The repository availability, response-contract clarity and released numerical analysis reproducibility can be closed after the public URL and fresh clone are verified. The broader comment is **partially addressed**: manuscript edits, unrestricted end-to-end access and permanent DOI archiving have not been completed and must not be reported as PASS.
