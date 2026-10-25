# Development and scientific validation

Offline synthetic tests only. Never invoke the `run --human-run` real-data
analysis during implementation. Metadata-only preflight is permitted. All test
screenplay text is purpose-written tiny synthetic text, not copied film text.

| Gate | PASS requirement |
|---|---|
| P00 | Taskset/feature/ledger/text/request contracts identified and paths inventoried |
| P01 | Synthetic filesystem loader, strict IDs, malformed/duplicate/missing bindings tested |
| P02 | Exact TI/DA reproduction on controlled fixtures; real compatibility remains unverified |
| P03 | All seven module implementations and their analytical-answer offline tests pass |
| P04 | Full synthetic pipeline passes V01–V15; negative invariant tests fail correctly |
| P05 | Persisted-result report generation works; synthetic/real report boundaries and seals tested |
| P06 | CLI, locks, documentation, source inventory and Git handoff complete |

V01 frozen task IDs/design; V02 observed model-condition counts and full exact
record replay; V03 zero-tolerance DA; V04 zero-threshold TI; V05 weighted A05/A03
DA; V06 A04/A03 missingness; V07 actual common-ID list/reference expectation;
V08 exhaustive denominators; V09 finite numeric results; V10 no missing input
becomes measured success; V11 scene/text identity and length eligibility;
V12 unchanged input hashes and absences; V13 persisted JSON/CSV agreement and
sealed-file report derivation; V14 actual source/dependency inference audit;
V15 explicit successful status for all seven modules. V13/V14 remain DEFERRED
in pure in-memory validation until the pipeline records concrete file/dependency
evidence. Any failure prevents full COMPLETE.

V05 alone allows 1e-14 absolute tolerance for differing floating-point summation
orders across groups. This never changes TI, direction signs, tolerance hits,
small-gain thresholds or full historical replay equality. No validator is
weakened to reproduce expected historical counts.

The optional local IEEEtran compiler has no installation fallback. Missing PDF
capability does not invalidate valid numerical analysis. All report sections,
CSV/JSON and Markdown tables remain available. Reports regenerate only into a
fresh directory and verify the computed-result seal first. A failed scientific
run leaves a clear report blocker instead of a fake successful research report.

Test commands (run from the shared workspace):

```bash
cd /home/alp-emre/projects/01-Storygen-area
PYTHONPATH="$PWD/storygen-experiment/experiments/reviewer_round1/e06_statistical_robustness/src:$PWD/storygen-experiment/experiments/reviewer_round1/e06_statistical_robustness/tests:$PWD/storygen-evaluation/evaluation/src" \
  python -m pytest storygen-experiment/experiments/reviewer_round1/e06_statistical_robustness/tests -q
python -m ruff check storygen-experiment/experiments/reviewer_round1/e06_statistical_robustness
```

Implementation status must remain IMPLEMENTATION_READY, HUMAN_RUN_PENDING and
SCIENTIFIC_RESULTS_NOT_YET_VERIFIED. Neither synthetic COMPLETE nor technical
execution completion establishes independent scientific acceptance.
