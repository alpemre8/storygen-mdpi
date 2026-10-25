# StoryGen Experiment

Independent version-locked experiments and their central orchestration. The four existing scientific engine repositories and all M13 native protocols remain intact. Every new run is written to the sibling storygen-experiment-depot; no universal scientific DAG is imposed.

Use the existing Python environment; no installation is needed: `python tools/experiments.py --help`. Public tools start the source package with a normal explicit subprocess PYTHONPATH. Experiment-specific code cannot import another experiment's private implementation.

Read EXPERIMENTS.md and docs/ for protocols and exact run instructions. Execution, contract integrity and scientific validity are separate. Migration verification remains UNVERIFIED. Raw scientific data remains local and is not backed up by Git metadata.

[Full research inspection and blockers](docs/FULL_RESEARCH_READINESS_REPORT.md) ·
[Operator commands](docs/OPERATOR_COMMANDS.md). Selected immutable target runs
are eligible for explicitly authorized private Git backup; verify actual remote
bytes with the documented workflow. Full machine-independent readiness is BLOCKED.

[Create and run an independent experiment](docs/CREATING_AND_RUNNING.md) ·
[Exact historical delegation and limitations](docs/historical-delegation.md) ·
[Experiment catalog and matching primaries](EXPERIMENTS.md)

The three acceptance protocols demonstrate different DAGs:
`future_research/reuse_only` (three frozen reference stages),
`future_research/custom_stage` (two owned synthetic stages), and
`future_research/cross_engine` (one owned input audit plus five frozen real stages).
Use `tools/new_experiment.py --template public_reference|local_engine` to start a
specification, then declare the scientific question and independent pipeline before
creation. No scientific engine source is duplicated into the central framework.
