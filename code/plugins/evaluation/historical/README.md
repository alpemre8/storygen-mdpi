# StoryGen Evaluation

Standalone owner of Evaluation `2.4.1`. All metric formulas, bootstrap logic,
aggregation, and paper-ready calculations are retained from `story_generation`.

New evaluations compare a reference/original `storygen.feature-set/1.4` with a
candidate/rewritten `storygen.feature-set/1.4`. The historical Evaluation entry
point remains readable for immutable `storygen.reanalysis-run/1.1` artifacts.

```bash
export STORYGEN_EVALUATION_DEPOT_ROOT="$HOME/projects/storygen-evaluation-depot"
python evaluation/cli/evaluate_run.py --help
```

All Evaluation CLI outputs must be inside `STORYGEN_EVALUATION_DEPOT_ROOT`.
