# E05-4-FEATURE-DIFF

Independent deterministic before/after feature comparison across all historical
TasksetV5 model-condition combinations. **Implementation only: no full real analysis
has been run. No LLM, rewrite, feature extraction or reanalysis is executed.**

Protocol: `E05_4_FEATURE_DIFF_V1` / `1.0.0`.
Population: 240 tasks × 4 models × 2 conditions = 1920 attempted records;
48 bases, ten films, 16000 scene slots. All missing historical outcomes remain visible.

The central DAG is PREPARE → VALIDATE → ANALYZE → REPORT. Owned Python modules in
`src/` implement exact input checks, coverage, numerical differences, task-weighted
matrices, paired and four-model intersections, cluster uncertainty, tables and plots.
Previous E05 experiments provide no scientific implementation or selection dependency.

- [Scientific protocol](SCIENTIFIC_PROTOCOL.md)
- [Actual input inventory](INPUT_BINDINGS.md)
- [Commands and output locations](COMMANDS.md)
- [Implementation and verification evidence](IMPLEMENTATION_REPORT.md)

Public runner: `./e05-feature-diff preflight|run|status|report`. One terminal,
CPU-only, bounded execution. Global installation is unnecessary. A successful run
leaves scientific validity UNVERIFIED; human agreement and semantic preservation
are not measured.
