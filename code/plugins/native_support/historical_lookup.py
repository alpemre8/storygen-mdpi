"""Relocate lookup only; keep original bytes, hashes and scientific validators."""

from contextlib import contextmanager
from pathlib import Path
import importlib
import importlib.util
from storygen_platform.engine.common import StoryGenError, file_sha
from storygen_platform.historical import HistoricalCatalog, restricted


@contextmanager
def lookup(root, depot, kind):
    spec = importlib.util.spec_from_file_location(
        "_sg_history_locations", Path(__file__).with_name("locations.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    locations = module.Locations(root, depot)
    catalog = HistoricalCatalog(depot)
    # This inventory is independent of the old absolute workspace location.
    expected = {}
    for row in catalog.index["runs"]:
        receipt = catalog.select(row["run_id"])
        for artifact in receipt["artifacts"]:
            expected[artifact["relative_path"]] = artifact["sha256"]

    def checked(recorded):
        original_path = Path(recorded)
        if original_path.parts and original_path.parts[0] == "runs":
            recorded = str(Path("/story_generation") / original_path)
        elif original_path.is_relative_to(Path(root)) and "runs" in original_path.parts:
            index = original_path.parts.index("runs")
            recorded = str(Path("/story_generation").joinpath(*original_path.parts[index:]))
        path = Path(locations.relocate(str(recorded))).resolve()
        if not path.is_relative_to(Path(depot).resolve()) or restricted(path):
            raise StoryGenError("Historical scientific input must resolve inside the open depot")
        relative = path.relative_to(Path(depot).resolve()).as_posix()
        if relative not in expected or file_sha(path) != expected[relative]:
            raise StoryGenError("Historical scientific input missing/changed: " + relative)
        return path

    if kind == "measurement":
        scientific = importlib.import_module("storygen_feature.rewritten")
        original = scientific.load_script

        def load_script(path):
            return original(checked(path))

        scientific.load_script = load_script
        try:
            yield
        finally:
            scientific.load_script = original
    elif kind == "evaluation":
        scientific = importlib.import_module("storygen_evaluation.feature_sets")
        provenance = importlib.import_module("storygen_evaluation.provenance")
        original = provenance.ArtifactResolver

        class Relocated(original):
            def file(self, recorded, sha):
                path = checked(recorded)
                return super().file(str(path), sha)

        provenance.ArtifactResolver = scientific.ArtifactResolver = Relocated
        try:
            yield
        finally:
            provenance.ArtifactResolver = scientific.ArtifactResolver = original
    else:
        raise StoryGenError("Unsupported historical lookup scope")


def for_context(context, kind):
    if not getattr(context, "historical_sources", None):
        return None
    return lambda: lookup(context.code_root, context.depot_root, kind)
