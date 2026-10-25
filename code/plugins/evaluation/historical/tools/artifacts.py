"""Inspect immutable new-run references and read-only historical locators."""
from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('artifact_registry_v2', ROOT / 'components/artifacts/v2/registry.py')
registry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(registry)

if __name__ == '__main__':
    raise SystemExit(registry.main())
