# Experiments

Generated from owner manifests, exact locks and sealed run metadata. Migration verification and synthetic runs are separate from research results.

## Research Analysis

- [reviewer_analysis](experiments/analysis/reviewer_analysis/reviewer_analysis.py) — Recompute deterministic A01–A10 reviewer analyses on immutable frozen inputs. [Protocol/docs](experiments/analysis/reviewer_analysis/README.md) · [exact locks](experiments/analysis/reviewer_analysis/dependencies.lock.yaml). Owner: `storygen-evaluation`. Stages: analyze. Research runs: none in new namespace. Migration verification: none. Scientific validity: **UNVERIFIED**.

Historical results stay in their original depots; exact read-only locators live in `catalogs/experiment_architecture_v1/legacy.jsonl`. A completed migration smoke is not a paper result.

Use `python tools/experiments.py list`, `show ID`, `doctor ID`, or the owner `plan/preflight/run/status` commands. Bound doctor requires `--config` and a fresh `--run-id`.

Create an independent experiment with `python tools/new_experiment.py --spec SPEC.json`. Compatible frozen stages are selected by exact version; only the studied behavior belongs in a new owned engine. See [creation guide](docs/architecture/EXPERIMENT_CREATION_GUIDE.md).
