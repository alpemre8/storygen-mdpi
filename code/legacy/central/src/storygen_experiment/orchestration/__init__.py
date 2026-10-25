"""Exclusive central execution and durable failure/interruption state."""

import json
import signal
import time
import traceback
from jsonschema import Draft202012Validator
from storygen_experiment import contracts, runtime, adapters
from storygen_experiment.planning import frozen_lock
from storygen_experiment.progress import Progress
from storygen_experiment.artifact_store import Store


def bindings(c, stage, outputs):
    result = {}
    for item in stage["inputs"]:
        ref = item["binding"]
        if "input" in ref:
            path = c["bound_inputs"][ref["input"]]
            expected = c["config"]["inputs"][ref["input"]]["sha256"]
        else:
            path, expected = outputs[ref["stage"], ref["output"]]
        if runtime.sha(path) != expected:
            raise RuntimeError("Input/upstream artifact drift: " + item["name"])
        result[item["name"]] = path
    return result


def execute(c, *, emit=True):
    # Preparation checks all adapter/provider bindings before allocation; failed preflight is not a run.
    state = adapters.prepare(c)
    store = Store(c["depot"], frozen_lock(c))
    store.create()
    root = store.root
    progress = Progress(
        root, c["manifest"]["experiment_id"], c["run_id"], c["stages"], emit=emit
    )
    receipts = []
    outputs = {}
    errors = []
    status = "COMPLETE"
    old_handlers = {}
    c["progress_tracker"] = progress

    def interrupted(signum, frame):
        raise InterruptedError("Owner received signal " + str(signum))

    for sig in [signal.SIGINT, signal.SIGTERM]:
        old_handlers[sig] = signal.signal(sig, interrupted)
    try:
        for stage in c["stages"]:
            key = stage["stage_id"]
            began = time.monotonic()
            receipt = dict(
                stage_id=key,
                provider=stage["provider"],
                status="RUNNING",
                started_utc=runtime.utc(),
                finished_utc=None,
                elapsed_seconds=0,
                outputs=[],
                error=None,
            )
            progress.update(key)
            runtime.exclusive_json(
                root / "stages" / key / "parsed/STARTED.json", receipt
            )
            try:
                for name, ref in c["config"].get("inputs", {}).items():
                    contracts.checked_file(ref)
                bound = bindings(c, stage, outputs)
                receipt["input_bindings"] = {
                    name: dict(path=str(p), sha256=runtime.sha(p))
                    for name, p in bound.items()
                }
                receipt["adapter"] = adapters.execute(c, stage, bound, state)
                for output in stage["outputs"]:
                    path = contracts.contained(
                        root, "stages/" + key + "/raw/" + output["path"]
                    )
                    value = json.loads(path.read_text())
                    Draft202012Validator(output["schema"]).validate(value)
                    digest = runtime.sha(path)
                    outputs[key, output["role"]] = (path, digest)
                    receipt["outputs"].append(
                        dict(
                            role=output["role"],
                            contract=output["contract"],
                            path=str(path.relative_to(root)),
                            sha256=digest,
                        )
                    )
                receipt["status"] = "COMPLETE"
                progress.finish(stage, time.monotonic() - began)
            except BaseException as exc:
                receipt.update(
                    status="INTERRUPTED"
                    if isinstance(exc, (InterruptedError, KeyboardInterrupt))
                    else "FAILED",
                    error=repr(exc),
                )
                raise
            finally:
                receipt.update(
                    finished_utc=runtime.utc(), elapsed_seconds=time.monotonic() - began
                )
                receipts.append(receipt)
                runtime.exclusive_json(
                    root / "stages" / key / "parsed/receipt.json", receipt
                )
    except BaseException as exc:
        status = (
            "INTERRUPTED"
            if isinstance(exc, (InterruptedError, KeyboardInterrupt))
            else "FAILED"
        )
        errors.append(dict(kind=type(exc).__name__, detail=str(exc)))
        progress.errors += 1
        runtime.exclusive(root / "logs/exception.log", traceback.format_exc().encode())
    finally:
        try:
            adapters.stop(state)
        except BaseException as exc:
            status = "FAILED"
            errors.append(dict(kind="OWNED_RESOURCE_CLEANUP", detail=repr(exc)))
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)
    # All bound inputs must still have their original identities before a success seal.
    for name, ref in c["config"].get("inputs", {}).items():
        try:
            contracts.checked_file(ref)
        except Exception as exc:
            status = "FAILED"
            errors.append(dict(kind="INPUT_INTEGRITY", name=name, detail=str(exc)))
    for (_, role), (path, digest) in outputs.items():
        if runtime.sha(path) != digest:
            status = "FAILED"
            errors.append(dict(kind="STAGE_OUTPUT_MUTATED", role=role, path=str(path)))
    unsafe = [str(p.relative_to(root)) for p in root.rglob("*") if p.is_symlink()]
    if unsafe:
        status = "FAILED"
        errors.append(dict(kind="UNSAFE_OUTPUT", paths=unsafe))
    progress.errors = len(errors)
    progress.update("FINISHED", status)
    return store.seal(status, receipts, errors)
