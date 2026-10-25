"""Primary owner for REVIEWER_ANALYSES_P01B_V1; frozen scientific implementation is dependency-locked."""
from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('owner_envelope_v4', ROOT / 'components/execution/v4/envelope.py')
envelope = importlib.util.module_from_spec(spec)
spec.loader.exec_module(envelope)

if __name__ == '__main__':
    raise SystemExit(envelope.owner_main(__file__, Path(__file__).parent / 'src/protocol.py'))
