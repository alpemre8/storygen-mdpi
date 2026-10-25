"""Local entry point for the versioned architecture-v2 technical distribution."""
from pathlib import Path
import importlib.util
import sys

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('storygen_registry_v2', ROOT / 'components/architecture/v2/registry.py')
registry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(registry)

if __name__ == '__main__':
    sys.exit(registry.main(default_repo=ROOT))
