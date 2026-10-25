"""Select exact frozen public components; metadata is not an engine copy."""

from pathlib import Path
import copy
import json
import os
import subprocess
import sys
from storygen_experiment import ROOT, runtime, contracts

PROJECT_MODULES = (
    "storygen",
    "storygen_taskset",
    "storygen_feature",
    "storygen_measurement_core",
    "storygen_evaluation",
    "storygen_naturalness",
)


def catalog():
    return json.loads(
        (ROOT / "src/storygen_experiment/reference_catalog.json").read_text()
    )


def module_allowed(name, components):
    return any(
        name == module or name.startswith(module + ".")
        for entry in components.values()
        for module in entry["python_modules"]
    )


def expand(spec):
    spec = copy.deepcopy(spec)
    requested = set(spec.get("reference_components", []))
    requested.update(
        s["adapter"]["component"]
        for s in spec["pipeline"]["stages"]
        if s["adapter"]["kind"] in {"public_call", "frozen_cli"}
    )
    if not requested:
        return spec, {}
    source = catalog()
    runtime.check_environment(source["environment"])
    pending = list(requested)
    chosen = {}
    while pending:
        key = pending.pop()
        if key in chosen:
            continue
        if key not in source["components"]:
            raise ValueError("Unknown frozen component/version: " + key)
        chosen[key] = source["components"][key]
        pending.extend(chosen[key].get("dependencies", []))
    reuse = spec["experiment"]["component_reuse"]
    reasons = {r["component"]: r for r in reuse}
    for key in requested:
        if (
            key not in reasons
            or reasons[key]["altered"]
            or not reasons[key]["rationale"].strip()
        ):
            raise ValueError(
                "Explicit scientific rationale for unchanged reference required: " + key
            )
    for key in sorted(set(chosen) - set(reasons)):
        reuse.append(
            dict(
                component=key,
                rationale="Unchanged mandatory frozen dependency of explicitly selected reference components",
                altered=False,
            )
        )
    dependencies = spec.setdefault("dependencies", {})
    providers = dependencies.setdefault("providers", [])
    for key, entry in sorted(chosen.items()):
        source_ref = entry["source"]
        provider = next(
            (
                p
                for p in providers
                if p["repo_id"] == source_ref["repo_id"]
                and p["commit"] == source_ref["commit"]
            ),
            None,
        )
        if provider is None:
            provider = {**source_ref, "components": []}
            providers.append(provider)
        component = {
            k: entry[k] for k in ["component_id", "version", "paths", "sha256"]
        }
        existing = next(
            (
                p
                for p in provider["components"]
                if p["component_id"] == component["component_id"]
            ),
            None,
        )
        if existing is not None and existing != component:
            raise ValueError("Conflicting component version lock")
        if existing is None:
            provider["components"].append(component)
    packages = set(spec.get("environment_packages", []))
    packages.update(source["environment"]["packages"])
    spec["environment_packages"] = sorted(packages)
    assets = spec.setdefault("scientific_assets", {})
    if "reference_selection.json" in assets:
        raise ValueError("Reference selection asset is creator-owned")
    assets["reference_selection.json"] = dict(
        schema_version="storygen.central-reference-selection/1.0",
        components=chosen,
        catalog_sha256=runtime.sha(
            ROOT / "src/storygen_experiment/reference_catalog.json"
        ),
        catalog_origin=source["central_metadata_origin"],
    )
    return spec, chosen


def selection(context):
    path = context["home"] / "src/assets/reference_selection.json"
    if not path.exists():
        return {}
    if "src/assets/reference_selection.json" not in context["lock"]["owner_assets"]:
        raise ValueError("Reference selection must be owner-locked")
    result = json.loads(path.read_text())["components"]
    for key, entry in result.items():
        ref = entry["source"]
        provider = next(
            (
                p
                for p in context["lock"]["providers"]
                if p["repo_id"] == ref["repo_id"] and p["commit"] == ref["commit"]
            ),
            None,
        )
        if provider is None or not any(
            all(
                c[k] == entry[k] for k in ["component_id", "version", "paths", "sha256"]
            )
            for c in provider["components"]
        ):
            raise ValueError("Selected component not exactly locked: " + key)
    return result


def component(context, stage):
    key = stage["adapter"]["component"]
    entries = selection(context)
    if key not in entries:
        raise ValueError("Stage uses an unselected component: " + key)
    entry = entries[key]
    if stage["provider"] != entry["repo_id"]:
        raise ValueError("Stage/reference provider mismatch")
    root = context["provider_versions"][
        entry["repo_id"] + "@" + entry["source"]["commit"]
    ]
    return entry, root


def environment(context):
    entries = selection(context)
    paths = []
    modules = {}
    for entry in entries.values():
        root = context["provider_versions"][
            entry["repo_id"] + "@" + entry["source"]["commit"]
        ]
        for rel in entry["python_paths"]:
            path = contracts.contained(root, rel)
            if not path.is_dir():
                raise ValueError("Missing public import root")
            if str(path) not in paths:
                paths.append(str(path))
        for module in entry["python_modules"]:
            if module in modules and modules[module] != str(root):
                raise ValueError("Ambiguous public module versions")
            modules[module] = str(root)
    env = runtime.clean_env()
    env["PYTHONPATH"] = os.pathsep.join(paths)
    for name in [
        "STORYGEN_REWRITE_DEPOT_ROOT",
        "STORYGEN_FEATURE_DEPOT_ROOT",
        "STORYGEN_EVALUATION_DEPOT_ROOT",
        "STORYGEN_NATURALNESS_DEPOT_ROOT",
    ]:
        env[name] = str(context["root"])
    if modules:
        code = (
            "import importlib.util,json; print(json.dumps({m:importlib.util.find_spec(m).origin for m in "
            + repr(list(modules))
            + "}))"
        )
        origins = json.loads(
            subprocess.check_output([sys.executable, "-c", code], env=env, text=True)
        )
        for name, path in origins.items():
            if path is None or not Path(path).resolve().is_relative_to(
                Path(modules[name]).resolve()
            ):
                raise RuntimeError("Editable/unpinned public module shadow: " + name)
        context["reference_metadata"] = dict(
            components=entries, import_origins=origins, python_paths=paths
        )
    return env


def validate_stage(context, stage):
    kind = stage["adapter"]["kind"]
    if kind not in {"public_call", "frozen_cli"}:
        return
    entry, root = component(context, stage)
    adapter = stage["adapter"]
    if kind == "public_call":
        if not module_allowed(adapter["module"], {adapter["component"]: entry}) or any(
            p.startswith("_") for p in adapter["module"].split(".")
        ):
            raise ValueError("Only selected public component modules may be called")
        if len(stage["outputs"]) != 1:
            raise ValueError("JSON public call requires exactly one declared result")
    else:
        interface = entry["interfaces"].get(adapter["script"])
        if interface is None:
            raise ValueError("CLI is not an advertised frozen public interface")
        if not set(interface["requires"]) <= {r["contract"] for r in stage["inputs"]}:
            raise ValueError("Frozen CLI input contracts are incompatible")
        if not set(interface["provides"]) <= {r["contract"] for r in stage["outputs"]}:
            raise ValueError("Frozen CLI output contracts are incompatible")
        if not contracts.contained(root, adapter["script"]).is_file():
            raise FileNotFoundError("Missing frozen CLI")
