"""Typed stage-oriented DAG planning; no scientific transformations here."""

from graphlib import TopologicalSorter, CycleError
from .common import StoryGenError, identifier


def plan(pipeline, registry):
    if pipeline.get("schema_version") != "storygen.pipeline/1":
        raise StoryGenError("Unsupported pipeline schema version")
    nodes = pipeline.get("nodes", [])
    if not nodes:
        raise StoryGenError("Pipeline requires explicit nodes")
    by_id = {}
    specs = {}
    for node in nodes:
        key = identifier(node["id"])
        if key in by_id:
            raise StoryGenError(f"Duplicate stage ID: {key}")
        by_id[key] = node
        provider = registry.get(node["provider"], node["version"])
        spec = provider.capability(node["capability"])
        if node["contract_version"] != spec["contract_version"]:
            raise StoryGenError(f"Unpinned contract version: {key}")
        if node["granularity"] not in spec["granularities"]:
            raise StoryGenError(f"Unsupported granularity: {key}")
        observations = node.get("observations_port")
        if observations is not None:
            port = spec["outputs"].get(observations)
            if port is None or port["semantic_type"] != "storygen.native-eligibility/1":
                raise StoryGenError(f"Invalid native eligibility output port: {key}")
        checks = node.get("native_checks_port")
        if checks is not None:
            port = spec["outputs"].get(checks)
            if port is None or port["semantic_type"] != "storygen.native-checks/1":
                raise StoryGenError(f"Invalid native scientific checks output port: {key}")
        specs[key] = spec
    dependencies = {}
    for key, node in by_id.items():
        incoming = node.get("inputs", {})
        spec = specs[key]
        if set(incoming) - set(spec["inputs"]):
            raise StoryGenError(f"Unknown input port in {key}")
        deps = set(node.get("depends_on", []))
        for name, port in spec["inputs"].items():
            if name not in incoming:
                if port["required"]:
                    raise StoryGenError(f"Missing required port {key}.{name}")
                continue
            binding = incoming[name]
            if set(binding) == {"input"}:
                try:
                    source = pipeline["inputs"][binding["input"]]
                except KeyError:
                    raise StoryGenError(f"Unresolved pipeline input: {binding}") from None
            elif set(binding) == {"stage", "port"}:
                source_id = binding["stage"]
                if source_id not in by_id:
                    raise StoryGenError(f"Unresolved upstream stage: {source_id}")
                deps.add(source_id)
                if node["granularity"] != by_id[source_id]["granularity"]:
                    raise StoryGenError(
                        "Cross-granularity wiring requires an explicit grouping plugin"
                    )
                try:
                    source = specs[source_id]["outputs"][binding["port"]]
                except KeyError:
                    raise StoryGenError(f"Unknown output port: {binding}") from None
            else:
                raise StoryGenError("Only explicit input or stage/port wiring is supported")
            if (
                source["semantic_type"] != port["semantic_type"]
                or source["schema"] != port["schema"]
            ):
                raise StoryGenError(
                    f"Type/shape/semantic mismatch at {key}.{name}; use a transformation plugin"
                )
        if deps - set(by_id):
            raise StoryGenError(f"Unknown dependencies in {key}")
        dependencies[key] = sorted(deps)
    try:
        ordering = list(TopologicalSorter(dependencies).static_order())
    except CycleError as exc:
        raise StoryGenError(f"Cyclic pipeline: {exc}") from exc
    return [by_id[key] for key in ordering]
