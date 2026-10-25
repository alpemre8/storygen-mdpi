"""Workspace manifest discovery is deliberately separate from approval."""

from pathlib import Path
import importlib.util
import jsonschema
from .common import StoryGenError, digest, identifier, read, tree_hash, contained

GRANULARITIES = {"TASK", "BATCH", "FILM", "DATASET"}


class Provider:
    def __init__(self, home):
        self.home = Path(home).resolve()
        self.manifest = read(self.home / "provider.yaml")
        m = self.manifest
        for key in ["provider_id", "version", "adapter", "capabilities"]:
            if key not in m:
                raise StoryGenError(f"Missing provider {key}: {home}")
        identifier(m["provider_id"])
        if not isinstance(m["version"], str) or not m["capabilities"]:
            raise StoryGenError("Provider version and capabilities required")
        self.state = "DISCOVERED"
        adapter_path = contained(self.home, m["adapter"].split(":")[0])
        self.adapter_path = adapter_path
        if not adapter_path.is_file():
            raise StoryGenError(f"Unresolvable adapter: {adapter_path}")
        for cap, spec in m["capabilities"].items():
            identifier(cap)
            if not set(spec["granularities"]) <= GRANULARITIES or not spec["granularities"]:
                raise StoryGenError(f"Invalid granularity: {cap}")
            for key in ["nature", "resources", "idempotent", "errors", "contract_version"]:
                if key not in spec:
                    raise StoryGenError(f"Missing capability field {cap}.{key}")
            if spec["nature"] not in {"deterministic", "inference", "historical"}:
                raise StoryGenError("Unknown execution nature")
            for direction in ["inputs", "outputs"]:
                for name, port in spec[direction].items():
                    identifier(name)
                    if not {"schema", "semantic_type", "required"} <= set(port):
                        raise StoryGenError(f"Incomplete typed port {cap}.{name}")
                    jsonschema.Draft202012Validator.check_schema(port["schema"])
        self.fingerprint = tree_hash(self.home, {".py", ".json", ".yaml", ".yml", ".txt", ".j2"})
        self._dependency_paths = {}
        code_root = self.home.parents[1]
        declared = set(m.get("scientific_sources", {}).values()) | set(
            m.get("scientific_dependencies", [])
        )
        for relative in sorted(declared):
            path = contained(code_root, relative)
            if not path.is_dir():
                raise StoryGenError("Missing declared scientific source dependency: " + relative)
            self._dependency_paths[relative] = (path, tree_hash(path))
        self._adapter = None
        self.state = "VALIDATED"

    def load(self):
        if self._adapter is None:
            spec = importlib.util.spec_from_file_location(
                "_sg_provider_" + self.fingerprint, self.adapter_path
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self._loaded_module = module
            self._adapter = getattr(module, self.manifest["adapter"].split(":")[1])
            if not callable(self._adapter):
                raise StoryGenError(f"Adapter is not callable: {self.adapter_path}")
        return self._adapter

    def preflight(self, capability, **context):
        name = self.capability(capability).get("preflight")
        if name is not None:
            identifier(name)
            self.load()
            return getattr(self._loaded_module, name)(capability, **context)

    def capability(self, name):
        try:
            return self.manifest["capabilities"][name]
        except KeyError:
            raise StoryGenError(
                f"Unknown capability {self.manifest['provider_id']}/{name}"
            ) from None

    def pin(self):
        current = tree_hash(self.home, {".py", ".json", ".yaml", ".yml", ".txt", ".j2"})
        if current != self.fingerprint:
            raise StoryGenError(
                "Provider source changed since discovery; rediscover and approve the new implementation"
            )
        dependencies = {}
        for relative, (path, expected) in self._dependency_paths.items():
            actual = tree_hash(path)
            if actual != expected:
                raise StoryGenError("Scientific dependency changed since discovery: " + relative)
            dependencies[relative] = actual
        return {
            "scientific_dependencies": dependencies,
            "provider_id": self.manifest["provider_id"],
            "version": self.manifest["version"],
            "fingerprint": self.fingerprint,
        }


class Registry:
    def __init__(self, roots):
        self.providers = {}
        for root in roots:
            for manifest in sorted(Path(root).glob("*/provider.yaml")):
                p = Provider(manifest.parent)
                key = p.manifest["provider_id"]
                if key in self.providers:
                    raise StoryGenError(f"Duplicate provider ID: {key}")
                self.providers[key] = p

    def get(self, key, version=None):
        if key not in self.providers:
            raise StoryGenError(f"Undiscovered provider: {key}")
        p = self.providers[key]
        if version is not None and version != p.manifest["version"]:
            raise StoryGenError(f"Provider version mismatch: {key}")
        return p

    def pins(self, pipeline):
        return {
            n["provider"]: self.get(n["provider"], n["version"]).pin() for n in pipeline["nodes"]
        }

    def approval_key(self, pipeline):
        return digest(self.pins(pipeline))
