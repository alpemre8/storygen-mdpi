"""Explicit immutable file references for constant DAG inputs, independent of science."""

from pathlib import Path
from copy import deepcopy
from .common import StoryGenError, contained, file_sha


def resolve(value, root, depot):
    if isinstance(value, dict):
        if "$historical" in value:
            from ..historical import HistoricalCatalog

            if set(value) != {"$historical", "path"}:
                raise StoryGenError("Historical binding requires an exact run ID and artifact path")
            ref = HistoricalCatalog(depot).artifact(value["$historical"], value["path"])
            return str(ref.resolve(depot))
        if "$directory" in value:
            if set(value) != {"$directory", "files"} or not value["files"]:
                raise StoryGenError("Directory binding requires explicit immutable file inventory")
            namespace, relative = value["$directory"].split(":", 1)
            base = {"code": Path(root), "depot": Path(depot)}.get(namespace)
            if base is None:
                raise StoryGenError("Unknown directory storage namespace")
            path = contained(base, relative)
            for name, expected in value["files"].items():
                actual = contained(path, name)
                if not actual.is_file() or file_sha(actual) != expected.removeprefix("sha256:"):
                    raise StoryGenError("Immutable directory member missing/changed: " + name)
            return str(path)
        if "$file" in value:
            if set(value) != {"$file", "sha256"}:
                raise StoryGenError("File binding requires exactly $file and sha256")
            uri = value["$file"]
            if not isinstance(uri, str) or ":" not in uri:
                raise StoryGenError("File binding needs code: or depot: storage URI")
            namespace, relative = uri.split(":", 1)
            base = {"code": Path(root), "depot": Path(depot)}.get(namespace)
            if base is None:
                raise StoryGenError("Unknown file storage namespace: " + namespace)
            path = contained(base, relative)
            if not path.is_file() or file_sha(path) != value["sha256"].removeprefix("sha256:"):
                raise StoryGenError("Immutable pipeline file missing/changed: " + uri)
            return str(path)
        return {k: resolve(v, root, depot) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, root, depot) for v in value]
    return deepcopy(value)
