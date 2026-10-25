"""Confined JSON call to a selected frozen public function; no scientific formulas."""

from pathlib import Path
import hashlib
import importlib
import json
import sys


def sha(path):
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    invocation = json.loads(Path(sys.argv[1]).read_text())

    def pointer(value, path):
        if path == "":
            return value
        if not path.startswith("/"):
            raise ValueError("JSON pointer must start with /")
        for token in path[1:].split("/"):
            token = token.replace("~1", "/").replace("~0", "~")
            value = value[int(token)] if isinstance(value, list) else value[token]
        return value

    def resolve(value):
        if isinstance(value, list):
            return [resolve(v) for v in value]
        if not isinstance(value, dict):
            return value
        if "input" in value or "stage" in value or "asset" in value:
            if "input" in value:
                ref = invocation["inputs"][value["input"]]
            elif "asset" in value:
                ref = invocation["assets"][value["asset"]]
            else:
                ref = invocation["upstream"][value["stage"] + ":" + value["output"]]
            path = Path(ref["path"])
            if sha(path) != ref["sha256"]:
                raise RuntimeError("Bound public-call input drift")
            return (
                path
                if value.get("as") == "path"
                else pointer(json.loads(path.read_text()), value.get("pointer", ""))
            )
        if value == {"output": True}:
            return Path(invocation["output_directory"])
        return {k: resolve(v) for k, v in value.items()}

    module = importlib.import_module(invocation["module"])
    origin = Path(module.__file__).resolve()
    if not origin.is_relative_to(Path(invocation["provider_root"]).resolve()):
        raise RuntimeError("Public callable imported outside pinned provider")
    function = getattr(module, invocation["function"])
    result = function(**resolve(invocation["arguments"]))
    payload = json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    Path(invocation["result"]).parent.mkdir(parents=True, exist_ok=True)
    with Path(invocation["result"]).open("x") as stream:
        stream.write(payload)
    with Path(invocation["origin_receipt"]).open("x") as stream:
        json.dump(
            dict(
                module=invocation["module"],
                function=invocation["function"],
                origin=str(origin),
                source_sha256=sha(origin),
            ),
            stream,
            indent=2,
        )


if __name__ == "__main__":
    main()
