"""Read-only historical provenance. Imported bytes never masquerade as engine events."""

from dataclasses import dataclass, asdict
from pathlib import Path
from .engine.common import StoryGenError, contained, digest, file_sha, read


def restricted(path):
    """Do not open sealed populations, even for hash verification."""
    parts = Path(path).parts
    return any("holdout" in p.lower() or "sealed" in p.lower() for p in parts)


@dataclass(frozen=True)
class ArtifactRef:
    run_id: str
    relative_path: str
    sha256: str
    bytes: int
    role: str
    origin: str = "HISTORICAL_IMPORTED"

    def resolve(self, depot):
        if self.origin != "HISTORICAL_IMPORTED" or restricted(self.relative_path):
            raise StoryGenError("Sealed or unsupported historical artifact access")
        path = contained(depot, self.relative_path)
        if not path.is_file() or path.stat().st_size != self.bytes or file_sha(path) != self.sha256:
            raise StoryGenError("Historical artifact missing/changed: " + self.relative_path)
        return path


class HistoricalCatalog:
    def __init__(self, depot):
        self.depot = Path(depot).resolve()
        self.index = read(self.depot / "migration/HISTORICAL_ARTIFACT_CATALOG.json")
        if self.index.get("schema") != "storygen.historical-catalog/1":
            raise StoryGenError("Unsupported historical catalog")
        self.runs = {r["run_id"]: r for r in self.index["runs"]}
        if len(self.runs) != len(self.index["runs"]):
            raise StoryGenError("Duplicate historical identity")

    def select(self, run_id):
        if run_id not in self.runs:
            raise StoryGenError("Choose an exact historical run ID; latest/aliases are forbidden")
        row = self.runs[run_id]
        path = contained(self.depot, row["receipt"])
        if file_sha(path) != row["receipt_sha256"]:
            raise StoryGenError("Historical receipt checksum mismatch")
        receipt = read(path)
        if receipt["run_id"] != run_id or receipt["origin"] != "HISTORICAL_IMPORTED":
            raise StoryGenError("Historical receipt identity mismatch")
        if digest(receipt["artifacts"]) != receipt["artifact_inventory_sha256"]:
            raise StoryGenError("Historical artifact inventory changed")
        return receipt

    def artifacts(self, run_id, *, role=None):
        return [
            ArtifactRef(run_id=run_id, **a)
            for a in self.select(run_id)["artifacts"]
            if role is None or a["role"] == role
        ]

    def artifact(self, run_id, relative_path):
        selected = [a for a in self.artifacts(run_id) if a.relative_path == relative_path]
        if len(selected) != 1:
            raise StoryGenError("Artifact must belong to the explicitly selected historical run")
        selected[0].resolve(self.depot)
        return selected[0]

    def verify(self, run_id, *, role=None):
        refs = self.artifacts(run_id, role=role)
        if not refs:
            raise StoryGenError("MISSING_OR_NOT_RECORDED: selected artifact role")
        verified = []
        for ref in refs:
            if restricted(ref.relative_path):
                verified.append(
                    {**asdict(ref), "verified_path": None, "status": "SEALED_INVENTORY_ONLY"}
                )
                continue
            verified.append({**asdict(ref), "verified_path": str(ref.resolve(self.depot))})
        return verified

    def port(self, run_id, relative_path, semantic_type):
        """Adapt a real manifest to an existing typed port, with separate provenance."""
        receipt = self.select(run_id)
        if receipt["qualification"] == "ENGINEERING_OR_TEST":
            raise StoryGenError("Engineering fixtures cannot be selected as scientific inputs")
        ref = self.artifact(run_id, relative_path)
        data = read(ref.resolve(self.depot))
        types = {
            "storygen.rewrite-run-ref/1.3": ("storygen.rewrite-run", "1.3"),
            "storygen.original-feature-set-ref/1.4": ("storygen.feature-set", "1.4"),
            "storygen.rewritten-feature-set-ref/1.4": ("storygen.feature-set", "1.4"),
            "storygen.taskset-runtime-ref/1.0": ("storygen.taskset-runtime", "1.0"),
        }
        legacy_taskset = (
            semantic_type == "storygen.taskset-runtime-ref/1.0"
            and "contract_id" not in data
            and data.get("taskset_id") == "tasksetv5"
        )
        if not legacy_taskset and (
            semantic_type not in types
            or (data.get("contract_id"), str(data.get("contract_version"))) != types[semantic_type]
        ):
            raise StoryGenError("Historical artifact contract differs from selected input port")
        value = {"path": str(ref.resolve(self.depot)), "sha256": ref.sha256}
        if semantic_type == "storygen.taskset-runtime-ref/1.0":
            from .engine.science_io import science_scope

            root = Path(__file__).resolve().parents[2]
            with science_scope(
                {"storygen_taskset": root / "plugins/rewrite/historical/taskset/src"}
            ):
                from storygen_taskset.builder import verify_taskset

                validation = verify_taskset(data, require_paths=False)
            if set(validation["errors"]) - ({"contract"} if legacy_taskset else set()):
                raise StoryGenError("Historical TasksetV5 structure is not canonical")
            value.update(
                task_count=len(data["tasks"]),
                base_interval_count=len({t["base_interval_id"] for t in data["tasks"]}),
                structure_sha256=validation["structure_sha256"],
                native_artifacts=[],
                validation={
                    **validation,
                    "origin": "HISTORICAL_IMPORTED",
                    "source_sha256": ref.sha256,
                    "legacy_unversioned_contract": legacy_taskset,
                },
            )
        elif semantic_type in {
            "storygen.rewrite-run-ref/1.3",
            "storygen.rewritten-feature-set-ref/1.4",
        }:
            if semantic_type == "storygen.rewritten-feature-set-ref/1.4":
                if data.get("source", {}).get("type") != "rewritten":
                    raise StoryGenError(
                        "Original measurements cannot be bound as rewritten measurements"
                    )
                candidates = [
                    e
                    for e in self.index["lineage"]
                    if e["from_run"] == run_id
                    and Path(e["artifact"]["relative_path"]).name == "rewrite_run_manifest.json"
                ]
                if not candidates:
                    raise StoryGenError(
                        "MISSING_OR_NOT_RECORDED: exact rewrite lineage for measurements"
                    )
                identities = set()
                for edge in candidates:
                    original = ArtifactRef(run_id=run_id, **edge["artifact"])
                    manifest = read(original.resolve(self.depot))
                    identities.add(
                        (
                            manifest.get("prompt_contract_id"),
                            manifest.get("model", {}).get("served_alias"),
                        )
                    )
                if len(identities) != 1:
                    raise StoryGenError("Ambiguous historical rewriting condition/model")
                strategy, model = identities.pop()
            else:
                strategy = data.get("prompt_contract_id")
                model = data.get("model", {}).get("served_alias")
            if strategy not in {"DP-v1", "CG-v1"} or not model:
                raise StoryGenError("MISSING_OR_NOT_RECORDED: exact DP/CG model identity")
            value.update(
                strategy=strategy,
                model=model,
                native_artifacts=[],
                summary={
                    "origin": "HISTORICAL_IMPORTED",
                    "observed_status": receipt["observed_status"],
                    "coverage": receipt["coverage"],
                },
            )
        elif data.get("source", {}).get("type") == "rewritten":
            raise StoryGenError("Rewritten measurements cannot be bound as original reference")
        return value

    def lineage(self, run_id):
        receipt = self.select(run_id)
        edges = [
            e for e in self.index["lineage"] if e["from_run"] == run_id or run_id in e["to_runs"]
        ]
        # Verify the exact source manifest AND each bound referenced byte, not a name match.
        for edge in edges:
            self.artifact(edge["from_run"], edge["evidence_path"])
            ref = ArtifactRef(run_id=edge["from_run"], **edge["artifact"])
            ref.resolve(self.depot)
        instruments = [e for e in self.index.get("instruments", []) if e["from_run"] == run_id]
        code = Path(__file__).resolve().parents[2]
        for item in instruments:
            path = contained(code, item["code_relative_path"])
            if (
                not path.is_file()
                or file_sha(path) != item["sha256"]
                or path.stat().st_size != item["bytes"]
            ):
                raise StoryGenError("Historical scientific instrument changed")
        return {
            "run": {k: v for k, v in receipt.items() if k != "artifacts"},
            "lineage": edges,
            "instruments": instruments,
            "inference_performed": False,
        }

    def list(self, experiment=None):
        rows = [
            r for r in self.index["runs"] if experiment is None or r["experiment"] == experiment
        ]
        # The list validates provenance receipts and primary manifests. Full verification is explicit.
        result = []
        for row in rows:
            receipt = self.select(row["run_id"])
            paths = []
            for artifact in receipt["artifacts"]:
                if artifact["role"] == "manifest" and not restricted(artifact["relative_path"]):
                    path = ArtifactRef(run_id=row["run_id"], **artifact).resolve(self.depot)
                    paths.append({"path": str(path), "sha256": artifact["sha256"]})
            result.append(
                {
                    **row,
                    "verified_manifest_paths": paths,
                    "verification_scope": "receipt and manifests; use historical verify for every open artifact",
                }
            )
        return result
