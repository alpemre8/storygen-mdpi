"""Technical import/transport binding. All scientific callables remain provider-owned.

A scope replaces only package lookup and HTTP transport, never scientific assets,
parsing, normalization, metrics or retry decisions. Scopes are serialized because
Python's import registry is process-wide. Native scientific schedulers keep their
own concurrency within the scope. An independent CLI run has its own process.
"""

from contextlib import contextmanager
from contextlib import nullcontext
from pathlib import Path
import importlib
import inspect
import sys
import threading
import httpx
from .common import StoryGenError, file_sha

_IMPORT_LOCK = threading.RLock()


@contextmanager
def standalone_scope(directory):
    """Resolve original bare sibling imports inside one declared source directory."""
    directory = Path(directory).resolve()
    names = {p.stem for p in directory.glob("*.py") if p.stem != "__init__"}
    if not names:
        raise StoryGenError("Standalone scientific source directory is empty")
    with _IMPORT_LOCK:
        saved = {n: m for n, m in sys.modules.items() if n.split(".")[0] in names}
        old_path = list(sys.path)
        for name in saved:
            del sys.modules[name]
        sys.path.insert(0, str(directory))
        try:
            yield
            for name in names:
                module = sys.modules.get(name)
                if module and not Path(module.__file__).resolve().is_relative_to(directory):
                    raise StoryGenError("Standalone scientific import escaped owned source")
        finally:
            for name in list(sys.modules):
                if name.split(".")[0] in names:
                    del sys.modules[name]
            sys.modules.update(saved)
            sys.path[:] = old_path


@contextmanager
def science_scope(roots, *, context=None, transport=None, endpoints=None):
    """Bind exact code roots and durably journal requests BEFORE native parsing.

    Tests may inject httpx.MockTransport explicitly. Production adapters never
    obtain a fake transport from run configuration or a runtime profile.
    """
    roots = {name: Path(path).resolve() for name, path in roots.items()}
    for name, path in roots.items():
        if not (path / name / "__init__.py").is_file():
            raise StoryGenError(f"Missing owned scientific package {name}: {path}")
    with _IMPORT_LOCK:
        old_path = list(sys.path)

        def names(n):
            return n.split(".")[0] in roots

        saved = {n: m for n, m in sys.modules.items() if names(n)}
        for name in saved:
            del sys.modules[name]
        sys.path[:0] = list(dict.fromkeys(str(p) for p in roots.values()))
        original_send = httpx.Client.send
        sequence_lock = threading.Lock()
        sequence = 0

        def send(client, request, *args, **kwargs):
            nonlocal sequence
            request.read()
            with sequence_lock:
                sequence += 1
                request_id = sequence
            # Preserve the actual scientific payload; only relocate its endpoint.
            canonical_url = str(request.url)
            for old, new in (endpoints or {}).items():
                if canonical_url == old or canonical_url.startswith(old.rstrip("/") + "/"):
                    request.url = httpx.URL(new.rstrip("/") + canonical_url[len(old.rstrip("/")) :])
                    request.headers["host"] = request.url.netloc.decode("ascii")
                    break
            request_record = {
                "kind": "NATIVE_REQUEST",
                "native_request_id": request_id,
                "canonical_url": canonical_url,
                "resolved_url": str(request.url),
                "method": request.method,
                "body": request.content.decode("utf-8"),
            }
            if context is not None:
                context.record_raw(request_record)
            try:
                if transport is None:
                    response = original_send(client, request, *args, **kwargs)
                else:
                    response = transport.handle_request(request)
                    response.request = request
                response.read()
                if context is not None:
                    context.record_raw(
                        {
                            "kind": "NATIVE_RESPONSE",
                            "native_request_id": request_id,
                            "status_code": response.status_code,
                            "body": response.text,
                        }
                    )
                return response
            except BaseException as exc:
                if context is not None:
                    context.record_raw(
                        {
                            "kind": "NATIVE_TRANSPORT_ERROR",
                            "native_request_id": request_id,
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        }
                    )
                raise

        httpx.Client.send = send
        try:
            for name, path in roots.items():
                module = importlib.import_module(name)
                if not Path(module.__file__).resolve().is_relative_to(path):
                    raise StoryGenError(f"Scientific import escaped owned code: {name}")
            yield
        finally:
            httpx.Client.send = original_send
            for name in list(sys.modules):
                if names(name):
                    del sys.modules[name]
            sys.modules.update(saved)
            sys.path[:] = old_path


def invoke(entrypoint, parameters, *, roots, context=None):
    """Invoke one declared original function; input conversion is explicit only."""
    module_name, attribute = entrypoint.split(":", 1)
    if module_name.split(".")[0] not in roots:
        raise StoryGenError("Callable is not in its declared scientific source packages")
    module = importlib.import_module(module_name)
    function = getattr(module, attribute)
    signature = inspect.signature(function)
    signature.bind(**parameters)
    source = Path(inspect.getsourcefile(function)).resolve()
    if not source.is_relative_to(Path(roots[module_name.split(".")[0]]).resolve()):
        raise StoryGenError("Actual scientific callable escaped provider-owned source")
    if context is not None:
        context.store.events.append(
            "NATIVE_CALL_STARTED",
            stage_id=context.node["id"],
            unit_id=context.unit_id,
            attempt_id=context.attempt_id,
            callable=entrypoint,
            source_sha256=file_sha(source),
            lock_hash=context.lock_hash,
        )
    return function(**parameters)


def json_value(value):
    """Lossless JSON-compatible native result, never arbitrary repr/fake values."""
    from dataclasses import is_dataclass, asdict

    if is_dataclass(value):
        return json_value(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(v) for v in value]
    if value is None or type(value) in {str, bool, int, float}:
        return value
    raise StoryGenError("Native result needs an explicit schema adapter: " + type(value).__name__)


def persist_native_artifacts(context):
    """Durably bind actual native files before the engine accepts an output."""
    import os
    from .common import sync_directory

    directory = Path(context.artifact_directory)
    refs = []
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise StoryGenError("Native output must not escape through a symlink")
        if path.is_file():
            with path.open("rb") as stream:
                os.fsync(stream.fileno())
            refs.append(
                {
                    "relative_path": path.relative_to(context.store.root).as_posix(),
                    "sha256": file_sha(path),
                    "bytes": path.stat().st_size,
                }
            )
    for parent in sorted(
        [directory, *[p for p in directory.rglob("*") if p.is_dir()]],
        key=lambda p: len(p.parts),
        reverse=True,
    ):
        sync_directory(parent)
    return refs


def call_declared(
    root,
    sources,
    entrypoint,
    parameters,
    *,
    context,
    path_parameters=(),
    supplied=None,
    lookup_scope=None,
):
    """Common technical glue; providers declare every callable and argument binding."""
    roots = {name: Path(root) / relative for name, relative in sources.items()}
    values = dict(parameters)
    for key in path_parameters:
        if key in values and values[key] is not None:
            values[key] = Path(values[key])
    for key, value in (supplied or {}).items():
        if key in values and values[key] != value:
            raise StoryGenError("Cannot override provider-owned argument: " + key)
        values[key] = value
    try:
        endpoints = {}
        role = getattr(context, "node", {}).get("model_role")
        if role is not None:
            cfg = context.profile["roles"][role]
            if "native_profile" in cfg:
                endpoints[cfg["native_profile"]["base_url"]] = (
                    f"http://{cfg['host']}:{cfg['port']}/v1"
                )
        with science_scope(roots, context=context, endpoints=endpoints):
            with lookup_scope() if lookup_scope else nullcontext():
                result = invoke(entrypoint, values, roots=roots, context=context)
    finally:
        artifacts = persist_native_artifacts(context)
        context.store.events.append(
            "NATIVE_ARTIFACTS_PERSISTED",
            stage_id=context.node["id"],
            unit_id=context.unit_id,
            attempt_id=context.attempt_id,
            artifacts=artifacts,
            lock_hash=context.lock_hash,
        )
    return {
        "result": {
            "value": json_value(result),
            "native_artifacts": artifacts,
            "callable": entrypoint,
        }
    }


def invoke_file(path, attribute, parameters, *, context, module=None):
    """Call an original standalone scientific component without copying its code."""
    import importlib.util

    source = Path(path).resolve()
    if module is None:
        name = "_sg_component_" + file_sha(source)
        spec = importlib.util.spec_from_file_location(name, source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    elif Path(module.__file__).resolve() != source:
        raise StoryGenError("Scoped standalone module differs from declared original source")
    function = getattr(module, attribute)
    inspect.signature(function).bind(**parameters)
    context.store.events.append(
        "NATIVE_CALL_STARTED",
        stage_id=context.node["id"],
        unit_id=context.unit_id,
        attempt_id=context.attempt_id,
        callable=str(source) + ":" + attribute,
        source_sha256=file_sha(source),
        lock_hash=context.lock_hash,
    )
    return function(**parameters)
