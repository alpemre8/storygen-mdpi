"""Technical compatibility for locked M13 command-form server profiles.

M13 v4 doctor assumes total_context_size. Some published E05 profiles instead
freeze --ctx-size inside command. Check that exact command without changing it
or the profile identity; all other original doctor gates still execute.
"""

from pathlib import Path
import json


def context_budget(profile):
    slots = profile["parallel_slots"]
    per = profile["context_per_slot"]
    if not isinstance(slots, int) or slots < 1 or not isinstance(per, int) or per < 1:
        raise ValueError("Invalid frozen context/slots")
    if "total_context_size" in profile:
        total = profile["total_context_size"]
    else:
        command = profile["command"]

        def option(name):
            if command.count(name) != 1:
                raise ValueError("Exact single command option required: " + name)
            return command[command.index(name) + 1]

        total = int(option("--ctx-size"))
        if int(option("--parallel")) != slots:
            raise ValueError("Command/profile slots mismatch")
        if (
            option("--host") != profile["host"]
            or int(option("--port")) != profile["port"]
        ):
            raise ValueError("Command/profile endpoint mismatch")
        if (
            Path(option("--model")).resolve() != Path(profile["model_path"]).resolve()
            or option("--alias") != profile["model_alias"]
        ):
            raise ValueError("Command/profile model mismatch")
        if Path(command[0]).resolve() != Path(profile["server_binary"]).resolve():
            raise ValueError("Command/profile binary mismatch")
    if total != slots * per:
        raise ValueError("Profile context/slots budget mismatch")
    return total


def doctor(envelope, context, plan):
    profiles = {
        stage["server_profile"]: json.loads(
            Path(context.input(stage["server_profile"])).read_text()
        )
        for stage in plan
        if stage.get("server_profile")
    }
    if not context.config.get("manage_servers", False) or all(
        "total_context_size" in p for p in profiles.values()
    ):
        envelope.doctor(context, plan)
        return "ORIGINAL_M13_V4_DOCTOR"
    # Keep original root checks and frozen resolver checks; validate command-form
    # profiles here because the unchanged M13 doctor cannot read this profile shape.
    envelope.doctor(
        context,
        [{k: v for k, v in stage.items() if k != "server_profile"} for stage in plan],
    )
    ports = set()
    for profile in profiles.values():
        if context.runtime.canonical_sha256(profile) not in context.lock[
            "scientific_invariants"
        ].get("allowed_server_profile_sha256", []):
            raise RuntimeError("Server profile is not locked")
        context_budget(profile)
        ports.add((profile["host"], profile["port"]))
    for host, port in ports:
        context.runtime.assert_port_available(port, host)
    return "M13_ROOT_DOCTOR_PLUS_EXACT_COMMAND_PROFILE_COMPATIBILITY_V1"
