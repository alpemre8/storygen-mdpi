# Verification performed for v1.0.1

Date: 25 October 2026. Python 3.12.3; exact installed distributions are listed in `ENVIRONMENT.txt` and pinned in `requirements-lock.txt`.

| Check | Actual result |
|---|---|
| Original E06 source loader / immutable input verification | PASS: 31,223 files, 240 tasks, 1,920 model/condition observations; no canonical replay mismatches; source inputs unchanged |
| Dependency installation in a new venv without system site packages | PASS: 36 pinned distributions installed; `pip check` found no broken requirements |
| Independent local Git clone outside the research workspace | PASS: tracked package cloned with `--no-local`; inherited PYTHONPATH/PYTHONHOME unset, user site disabled |
| Full release file inventory and SHA-256 verification in that clone | PASS |
| Executable measurement schema and invalid-response examples | PASS |
| Manuscript Tables 6–10 and 500 reliability observations | PASS: recorded table values reproduced |
| E01-B nine coverage and point-estimate cells | PASS; archived reviewer confidence/agreement results supplied separately |
| E02 summaries and confidence intervals | PASS using original analysis kernel |
| E03 repeatability and DP48 extension | PASS using original 10,000-resample kernels |
| E04 matched DIR/NUM analysis | PASS using original 10,000-resample kernel |
| E05-4 feature difference | PASS: ten tables from 16,000 slots / 1,920 planned task combinations; original 2,000-resample bootstrap |
| E06 A01–A07 | PASS: thirty numeric tables and canonical curve metrics; private reference columns omitted from comparison |
| Original selected source tests in the clean clone | PASS: 61 passed, 0 failed, 0 skipped |
| Public export scope and automated content scan | PASS; see `PUBLIC_EXPORT_AUDIT.json` for scope and limits |
| Live model inference, GPU experiments, new generation | NOT RUN |
| Bounded independent E01 preparation | Historical NOT_EXECUTED/HUMAN_RUN_PENDING state retained |
| Full restricted-text end-to-end reproduction from public files alone | NOT AVAILABLE |
| Zenodo deposition / DOI | NOT CREATED |

The checked clone contained the exact released scientific code, data and replay kernels. Final documentation, provenance inventory labels and checksum entries were finalized afterward; these do not alter scientific observations or analysis results. The numerical replay report is `REPRODUCTION_REPORT.json`. Original artifacts are kept separate from recomputed results. New runs must choose a new output directory. The release's CI workflow reruns the same checks on GitHub; remote workflow status is reported separately and is not inferred from local success.

The initial GitHub v1.0.0 run exposed an absolute Python path in the inherited E05-4 shell launcher (60 passed, 1 failed after all numerical replays passed). v1.0.1 replaces only that default with the active PATH interpreter; see `docs/RELEASE_PATCHES.md`. GitHub execution evidence for the corrected tag is supplied as a release verification attachment.
