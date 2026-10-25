"""Technical path lookup binding for original evaluation provenance validators."""

from contextlib import contextmanager
from pathlib import Path
import importlib
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "_sg_owned_locations", Path(__file__).resolve().parents[1] / "native_support/locations.py"
)
_locations = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_locations)
Locations = _locations.Locations


@contextmanager
def resolver_scope(locations):
    """Bind only the original resolver's path lookup, keeping all original validators."""
    module = importlib.import_module("storygen_evaluation.provenance")
    original = module.ArtifactResolver

    class Overrides(dict):
        def get(self, key, default=None):
            return locations.relocate(super().get(key, key if default is None else default))

    class RelocatedResolver(original):
        def __init__(self, overrides=None):
            super().__init__(overrides)
            self.overrides = Overrides(
                {k: locations.relocate(v) for k, v in self.overrides.items()}
            )

    module.ArtifactResolver = RelocatedResolver
    try:
        yield
    finally:
        module.ArtifactResolver = original
