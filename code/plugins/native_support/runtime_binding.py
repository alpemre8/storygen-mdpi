"""Versioned location/transport binding; original scientific server flags stay fixed."""

from pathlib import Path
import importlib.util
from storygen_platform.engine.common import StoryGenError, read, file_sha


def qualify(root, cfg, *, kind):
    root = Path(root)
    profiles = read(
        root / "plugins/rewrite/historical/components/tasksetv5/v1/SERVER_PROFILES.json"
    )
    candidates = profiles["rewrite"] if kind == "rewrite" else [profiles["measurement"]]
    selected = [
        p
        for p in candidates
        if p["model_sha256"].removeprefix("sha256:") == cfg["sha256"]
        and p["model_alias"] == cfg["identity"]
        and p["quantization"] == cfg["quantization"]
    ]
    if len(selected) != 1:
        raise StoryGenError("Model/precision is not an original " + kind + " instrument profile")
    canonical = selected[0]
    return qualify_exact(
        root,
        cfg,
        canonical,
        source_identity=file_sha(
            root / "plugins/rewrite/historical/components/tasksetv5/v1/SERVER_PROFILES.json"
        ),
    )


def qualify_exact(root, cfg, canonical, *, source_identity):
    root = Path(root)
    if (
        canonical["model_sha256"].removeprefix("sha256:") != cfg["sha256"]
        or canonical["model_alias"] != cfg["identity"]
        or canonical["quantization"] != cfg["quantization"]
    ):
        raise StoryGenError("Exact native model/alias/precision identity required")
    if cfg.get("backend_source_commit") != canonical["llama_cpp_commit"]:
        raise StoryGenError("Native instrument backend commit differs from frozen source")
    source = root / "plugins/rewrite/historical/components/runtime/v1/legacy_technical.py"
    spec = importlib.util.spec_from_file_location(
        "_sg_original_runtime_" + file_sha(source), source
    )
    original = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(original)
    expected = canonical.get("command") or original.server_command(canonical)
    if "--offline" not in expected:
        expected = [expected[0], "--offline", *expected[1:]]

    def options(command):
        result = {}
        i = 1
        aliases = {"-m": "--model", "-c": "--ctx-size", "-np": "--parallel"}
        while i < len(command):
            key = aliases.get(command[i], command[i])
            if key in result:
                raise StoryGenError("Duplicate native backend option: " + key)
            if i + 1 < len(command) and not command[i + 1].startswith("-"):
                result[key] = command[i + 1]
                i += 2
            else:
                result[key] = True
                i += 1
        return result

    want, actual = options(expected), options(cfg["command"])
    # Only physical paths/endpoints/device and CPU scheduling may be rebound.
    relocatable = {
        "--model",
        "--host",
        "--port",
        "--device",
        "--threads",
        "--threads-batch",
        "--threads-http",
    }
    if {k: v for k, v in want.items() if k not in relocatable} != {
        k: v for k, v in actual.items() if k not in relocatable
    }:
        raise StoryGenError(
            "Scientifically consequential native server flags differ from frozen profile (slots/context/KV/batch/decoding)"
        )
    cfg["native_profile"] = canonical
    cfg["native_binding"] = {
        "version": "native-location-binding/1",
        "canonical_profile_source_sha256": source_identity,
        "canonical_command": expected,
        "actual_command": cfg["command"],
        "relocatable_fields": sorted(relocatable),
    }
    return canonical
