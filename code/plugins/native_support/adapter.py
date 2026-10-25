"""Provider-owned offline inspection; never a scientific inference adapter."""

from pathlib import Path
import importlib.util
from storygen_platform.engine.common import StoryGenError


def execute(capability, inputs, context):
    if capability != "inspect" or getattr(context, "operation", None) != "INSPECT_NO_INFERENCE":
        raise StoryGenError(
            "Native inspection adapter is read-only planning, not a runnable scientific stage"
        )
    path = Path(__file__).with_name("planning.py")
    spec = importlib.util.spec_from_file_location("_sg_owned_native_inspection", path)
    planner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(planner)
    return {
        "plan": planner.inspect(
            inputs["definition"], context.code_root, context.depot_root, context.configuration
        )
    }
