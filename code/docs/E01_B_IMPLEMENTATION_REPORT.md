# E01-B implementation and offline validation

Status: implementation complete; real Mistral Q4 measurements **PENDING / AUTHOR ONLY**. No model download, dependency installation, live inference HTTP, real server start, rewrite generation or benchmark was performed by Codex.

The request is the E01-B continuation supplied on 2026-10-23. It authorizes three new phases while retaining the existing E01. The previous migration's restriction against inventing unrequested experiments does not prevent this explicitly requested continuation. Only the active `storygen` and `storygen-depot` repositories are modified; the original ten repositories and historical experiment/results files remain unchanged.

## Delivered behavior

- Three native engine definitions: `e01_b1_cross_model_precision`, `e01_b2_cross_model_precision`, `e01_b3_cross_model_precision`. B1 measures existing Qwen DP/CG; B2 Gemma CG; B3 Gemma DP. No stage launches another phase.
- Dedicated provider `plugins/e01_b`, using original `CanonicalFeatureScorer`, `GlobalSceneScheduler`, `MeasurementProtocol`, E01 independent B/T alignment, canonical `metrics.evaluate_task`, and original cluster-bootstrap implementation.
- Frozen depot input manifest with imported hash/receipt lineage. Original source/reference scenes, 240 task IDs, rewrite scene order, generation transfer plans, model identities and historical controls are verified. Full preparation verifies 5,526 open files. Sealed payloads are not read.
- B1-only validation requires its shared originals and Qwen inputs; it does not read optional Gemma/FP16 payloads. New original measurements are local to each phase, keeping phases independent.
- Same Qwen measurement server argv except model path/alias, with GGUF Q4_K_M and architecture verification. Prompt/schema/features, sampling, retry, validation and normalization remain unchanged. Existing llama.cpp Mistral system-message compatibility is documented; no template override is introduced.
- Two-terminal operation with an owned server session, machine-wide GPU lease, PID/start-time/executable/argv attestation, live identity/context checks on author-run attachment, and a single client lease. Existing default owned-server execution remains available and unchanged for other experiments.
- One progress renderer, percent/count/elapsed/ETA in `HH:MM:SS`; detailed logs and native raw requests/responses are files. ETA uses observed newly completed jobs, excluding reused checkpoints.
- Per-scene same-run checkpoints plus original engine journals/run locks. A saved result is reused without inference; a started request with no saved result is treated as ambiguous and requires a new run rather than silent reissue. No completed run/report is overwritten.
- Nine-row Markdown/CSV/JSON comparison, four pending Mistral Q4 combinations at preparation, explicit matched eligible task sets, TI/DA/gain/distances, extractor and CG−DP comparisons, precision comparison, confidence intervals and exact ineligibility reasons. FP16 runtime differences are included in the report.

The generic engine changes are limited to an optional explicitly allowed manual server session; the normal execution branch is retained. CLI adds `e01-b` and suppresses Git worktree setup chatter. Existing E01 definitions, instruments and scientific functions are untouched.

## Validation

| Check | Result | Evidence |
|---|---|---|
| Three actual-data technical preflights | PASS, 240 tasks each; offline | Final committed-head CLI evidence in depot `migration/e01_b_evidence/` |
| Actual source/input alignment and SHA checks | PASS, 5,526 open files | New dataset `PREPARATION_VALIDATION-*.json` |
| Selected shared-engine/scientific regressions | **125 passed**, zero failures/skips, 276.66 seconds | `migration/e01_b_evidence/storygen-e01-b-regression.xml` |
| Final E01-B focused suite | **9 passed**, zero failures/skips, 22.88 seconds | `migration/e01_b_evidence/storygen-e01-b-final.xml` |
| Lint and whitespace | PASS | Ruff on new Python files; `git diff --check` |
| Real LLM/server/GPU qualification | NOT RUN | Researcher runs the commands in the operator guide |

The 9 focused cases are included in the selected regression scope; these counts must not be added to claim 134 distinct tests. The complete unrelated E05/E03/E04 heavy suite was not rerun for this change. Original algorithms for those experiments were not edited.

The focused tests deny live socket connections and model process launches. They execute all three actual native phase paths on clearly labelled temporary synthetic fixtures, with fake transport and injected server lifecycle. Tests cover invalid-first-response native retry/raw persistence; independent B/T golden parity against the old E01 handoff; matched population rejection; scene failures; original 240-task real-data preflights; exact server parameter drift; GGUF/template compatibility; interruption after output persistence and resume with **no additional HTTP request**; committed/native/checkpoint tamper rejection; pending cells; precision contrast; manual session identity/client lock; phase independence; and absence of terminal JSON/log chatter.

During development, the new resume test exposed the existing engine requirement that an inference attempt persist raw/provenance evidence even when every result is cached. The provider now journals explicit validated-checkpoint reuse linked to original raw records. It does not manufacture a model response or claim new inference. The failed development JUnit run is retained beside the passing runs.

## Historical coverage and precision limit

| Historical rewrite condition | Existing rewrites / attempted tasks |
|---|---|
| Qwen DP-v1 | 239 / 240 |
| Qwen CG-v1 | 235 / 240 |
| Gemma DP-v1 | 239 / 240 |
| Gemma CG-v1 | 238 / 240 |
| Existing Gemma CG Mistral FP16 measurement | 238 eligible / 240 |

Missing original task IDs remain in the frozen input manifest and new reports. Conditional table means are descriptive for each row's eligible population; paired statistics use only explicit common eligible IDs and report both matched denominators and matched means.

The historical FP16 runtime used context/slot 9,216, batch 512, ubatch 128, GPU layers 16. The requested Q4 runtime keeps Qwen's context/slot 12,288, batch 16,384, ubatch 2,048 and original binary-default GPU offloading. Therefore FP16 versus Q4 is a descriptive cross-runtime comparison, not an isolated causal precision experiment.

The preparation report at depot `reports/e01_b/preparation-20261023/REPORT.md` reads existing historical results only. Its four Mistral Q4 combinations are `PENDING`; no missing result is estimated. There are no real E01-B extraction runs yet.

## Operator handoff and storage

Copyable commands, exact model/protocol differences, retry/ETA semantics, recovery commands and all output locations are in [E01_B_OPERATOR_GUIDE.md](E01_B_OPERATOR_GUIDE.md).

Source changes are committed to the existing code branch. Implementation approvals are registered for the committed engine/provider combination from deterministic evidence. Current-head preflight receipts, code/depot commit references and command exit codes are stored in the depot evidence directory after the source commit. The depot is locally committed only; its existing unconditional remote-publication block is unchanged.
