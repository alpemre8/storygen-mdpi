"""Read-only provenance view derived from the actual active DAG and provider contracts."""

from pathlib import Path
from . import dag
from .common import contained, file_sha
from .bindings import resolve


def describe(root, depot, home, definition, pipeline, registry):
    root = Path(root)
    stages = []
    for node in dag.plan(pipeline, registry):
        provider = registry.get(node["provider"], node["version"])
        cap = provider.capability(node["capability"])
        sources = []
        for relative in cap.get(
            "source_paths", [cap["source_path"]] if cap.get("source_path") else []
        ):
            path = contained(root, relative)
            sources.append({"path": relative, "sha256": file_sha(path)})
        stages.append(
            {
                **node,
                "adapter": str(provider.adapter_path.relative_to(root)),
                "adapter_sha256": file_sha(provider.adapter_path),
                "scientific_callable": cap.get("scientific_callable"),
                "scientific_sources": sources,
                "contract": cap,
                "implementation": provider.pin(),
            }
        )
    resolved = resolve(definition.get("bindings", {}), root, depot)
    return {
        "experiment_id": definition["experiment_id"],
        "status": "ACTIVE_TYPED_PIPELINE",
        "readiness": definition["readiness"],
        "execution_performed": False,
        "population": definition["population"],
        "design": definition.get("design"),
        "nodes": stages,
        "input_references": definition.get("bindings", {}),
        "resolved_inputs": resolved,
        "instruments": definition["instruments"],
        "definition_files": [
            {"path": str(Path(home) / n), "sha256": file_sha(Path(home) / n)}
            for n in ["experiment.yaml", "pipeline.yaml"]
        ],
        "qualification": "Port/source/input resolution only; no inference or scientific result is asserted",
    }
