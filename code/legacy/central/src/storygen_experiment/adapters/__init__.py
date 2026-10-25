"""Technical stage adapters. Scientific engines are supplied by frozen providers."""

from pathlib import Path
import json
import time
from storygen_experiment import runtime, references


def prepare(context):
    from .native import Native

    keys = {
        s["adapter"]["delegate"]
        for s in context["stages"]
        if s["adapter"]["kind"] == "m13_stage"
    }
    for stage in context["stages"]:
        if stage["adapter"]["kind"] not in {
            "synthetic",
            "m13_stage",
            "local_engine",
            "frozen_cli",
            "public_call",
        }:
            raise ValueError("Adapter is not available: " + stage["adapter"]["kind"])
        references.validate_stage(context, stage)
    env = references.environment(context)
    return dict(
        native={key: Native(context, key) for key in sorted(keys)},
        providers=context["providers"],
        reference_env=env,
    )


def synthetic(context, stage, bindings):
    adapter = stage["adapter"]
    raw = context["root"] / "stages" / stage["stage_id"] / "raw"
    params = adapter["parameters"]
    operation = adapter["operation"]
    if operation == "fail":
        runtime.exclusive_json(raw / "partial.json", dict(partial=True))
        raise RuntimeError("Explicit injected synthetic stage failure")
    if operation == "sleep":
        time.sleep(float(params.get("seconds", 1)))
    value = dict(params.get("value", {"value": 1}))
    if bindings and params.get("copy_input"):
        value = json.loads(next(iter(bindings.values())).read_text())
    runtime.exclusive_json(raw / stage["outputs"][0]["path"], value)
    return dict(adapter="synthetic", model_requests=0)


def execute(context, stage, bindings, state):
    kind = stage["adapter"]["kind"]
    if kind == "synthetic":
        return synthetic(context, stage, bindings)
    if kind == "m13_stage":
        return state["native"][stage["adapter"]["delegate"]].execute(
            stage, runtime.run_command
        )
    if kind == "local_engine":
        return local_engine(context, stage, bindings, state)
    if kind in {"frozen_cli", "public_call"}:
        return frozen_reference(context, stage, bindings, state)
    raise ValueError("Adapter not implemented in this phase: " + kind)


def stop(state):
    for native in state.get("native", {}).values():
        native.stop()


def arguments(context, stage, bindings):
    def value(arg):
        if isinstance(arg, (str, int, float, bool)):
            return str(arg)
        if set(arg) == {"output"} and arg["output"] is True:
            return str(context["root"] / "stages" / stage["stage_id"] / "raw")
        if set(arg) == {"run_id"} and arg["run_id"] is True:
            return context["run_id"]
        if "input" in arg:
            path = context["bound_inputs"][arg["input"]]
            if arg.get("parent"):
                if (
                    context["config"]["inputs"][arg["input"]]
                    .get("origin", {})
                    .get("kind")
                    != "central"
                ):
                    raise ValueError(
                        "Directory binding requires a sealed central parent run"
                    )
                path = path.parent
            return str(path)
        if set(arg) == {"config"}:
            item = context["config"].get("parameters", {})[arg["config"]]
            if (
                not isinstance(item, (str, int, float, bool))
                or isinstance(item, str)
                and item.startswith("/")
            ):
                raise ValueError(
                    "Scalar non-path config binding required; bind file inputs explicitly"
                )
            return str(item)
        if set(arg) == {"asset"}:
            return str(runtime.contained(context["home"], "src/assets/" + arg["asset"]))
        if set(arg) == {"stage", "output"}:
            source = next(s for s in context["stages"] if s["stage_id"] == arg["stage"])
            output = next(o for o in source["outputs"] if o["role"] == arg["output"])
            return str(
                runtime.contained(
                    context["root"],
                    "stages/" + source["stage_id"] + "/raw/" + output["path"],
                )
            )
        raise ValueError("Unknown typed argv binding")

    return [value(a) for a in stage["adapter"].get("arguments", [])]


def local_engine(context, stage, bindings, state):
    import sys

    engine = runtime.contained(context["home"], stage["adapter"]["engine"])
    if str(engine.relative_to(context["home"])) not in context["lock"]["owner_assets"]:
        raise ValueError("Local engine is not hash-locked")
    env = state["reference_env"]
    result = runtime.run_command(
        context,
        stage,
        [sys.executable, str(engine), *arguments(context, stage, bindings)],
        context["home"],
        env,
    )
    return {
        **result,
        "engine_sha256": runtime.sha(engine),
        "engine_version": stage["adapter"]["version"],
        "output_mode": "DIRECT_CENTRAL_RUN",
        "write_confinement": "LINUX_LANDLOCK_RUN_ROOT",
    }


def frozen_reference(context, stage, bindings, state):
    import sys

    entry, provider = references.component(context, stage)
    adapter = stage["adapter"]
    raw = context["root"] / "stages" / stage["stage_id"] / "raw"
    if adapter["kind"] == "frozen_cli":
        command = [
            sys.executable,
            str(runtime.contained(provider, adapter["script"])),
            *arguments(context, stage, bindings),
        ]
    else:
        inputs = {
            name: dict(path=str(path), sha256=runtime.sha(path))
            for name, path in context["bound_inputs"].items()
        }
        upstream = {}
        assets = {}
        for node in context["stages"]:
            for output in node["outputs"]:
                path = (
                    context["root"]
                    / "stages"
                    / node["stage_id"]
                    / "raw"
                    / output["path"]
                )
                if path.is_file():
                    upstream[node["stage_id"] + ":" + output["role"]] = dict(
                        path=str(path), sha256=runtime.sha(path)
                    )
        for rel, digest in context["lock"]["owner_assets"].items():
            if rel.startswith("src/assets/"):
                assets[rel.removeprefix("src/assets/")] = dict(
                    path=str(context["home"] / rel), sha256=digest
                )
        invocation = dict(
            module=adapter["module"],
            function=adapter["function"],
            arguments=adapter["arguments"],
            inputs=inputs,
            upstream=upstream,
            assets=assets,
            provider_root=str(provider),
            output_directory=str(raw),
            result=str(raw / stage["outputs"][0]["path"]),
            origin_receipt=str(
                context["root"]
                / "stages"
                / stage["stage_id"]
                / "parsed/import_origin.json"
            ),
        )
        path = (
            context["root"]
            / "stages"
            / stage["stage_id"]
            / "parsed/public_invocation.json"
        )
        runtime.exclusive_json(path, invocation)
        command = [
            sys.executable,
            str(Path(__file__).with_name("public_worker.py")),
            str(path),
        ]
    result = runtime.run_command(
        context, stage, command, provider, state["reference_env"]
    )
    return {
        **result,
        "component": adapter["component"],
        "source_commit": entry["source"]["commit"],
        "component_sha256": entry["sha256"],
        "write_confinement": "LINUX_LANDLOCK_RUN_ROOT",
        "output_mode": "DIRECT_CENTRAL_RUN",
    }
