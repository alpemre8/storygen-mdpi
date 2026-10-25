# Validation

- Python source compilation: passed.
- Block unit tests: passed.
- Contract version: matches block.yaml and VERSION.
- Combined deterministic pipeline smoke: passed for Feature(original) -> Rewrite -> Feature(rewritten) -> Evaluation with a fake scorer and no model server.


- Direction generation has no threshold/deadband: any positive delta maps to increase, any negative delta maps to decrease, and zero maps to maintain.
