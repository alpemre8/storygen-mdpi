"""One exclusive central run namespace; raw data and safe Git metadata stay separate."""

from pathlib import Path
import json
import os
from storygen_experiment import contracts, runtime


def run_root(depot, group, experiment, run_id):
    contracts.identifier(run_id)
    contracts.relative(group)
    contracts.relative(experiment)
    return contracts.contained(
        Path(depot), f"experiments/{group}/{experiment}/runs/{run_id}"
    )


def checked_depot(path):
    path = Path(path).resolve()
    v = json.loads((path / "DEPOT_MANIFEST.json").read_text())
    if (
        v["depot_id"] != "storygen-experiment-depot"
        or v["owner"] != "storygen-experiment"
    ):
        raise ValueError("Central depot identity required")
    return path


class Store:
    def __init__(self, depot, lock):
        self.depot = checked_depot(depot)
        self.lock = lock
        self.manifest = lock["experiment"]
        self.root = run_root(
            self.depot,
            self.manifest["group_id"],
            self.manifest["experiment_id"],
            lock["run_id"],
        )

    def create(self):
        self.root.parent.mkdir(parents=True, exist_ok=True)
        self.root.mkdir(exist_ok=False)
        for path in ["inputs", "stages", "logs", "reports", "integrity"]:
            (self.root / path).mkdir()
        for stage in self.lock["pipeline"]["stages"]:
            for path in ["raw", "parsed"]:
                contracts.contained(
                    self.root, "stages/" + stage["stage_id"] + "/" + path
                ).mkdir(parents=True)
        runtime.exclusive_json(self.root / "run.lock.json", self.lock)
        runtime.exclusive_json(
            self.root / "RUN_STARTED.json",
            dict(
                run_id=self.lock["run_id"],
                started_utc=runtime.utc(),
                owner_process=runtime.identity(),
                lock_sha256=runtime.sha(self.root / "run.lock.json"),
            ),
        )
        runtime.exclusive_json(
            self.root / "inputs/exact_configuration.json", self.lock["configuration"]
        )
        return self

    def seal(self, status, stages, errors):
        if (self.root / "integrity/SEALED.json").exists() or (
            self.root / "run_manifest.json"
        ).exists():
            raise FileExistsError("Terminal run is immutable")
        artifacts = []
        rejected = []
        providers = {
            s["stage_id"]: s["provider"] for s in self.lock["pipeline"]["stages"]
        }
        for path in sorted(self.root.rglob("*")):
            if path.is_symlink():
                rejected.append(
                    dict(
                        path=str(path.relative_to(self.root)), target=os.readlink(path)
                    )
                )
                continue
            if not path.is_file():
                continue
            relative = str(path.relative_to(self.root))
            parts = path.relative_to(self.root).parts
            producer = (
                providers.get(parts[1], "storygen-experiment")
                if parts[0] == "stages" and len(parts) > 1
                else "storygen-experiment"
            )
            for ownership in sorted(
                self.lock.get("output_ownership", []),
                key=lambda x: len(x["relative_prefix"]),
                reverse=True,
            ):
                if Path(relative).is_relative_to(ownership["relative_prefix"]):
                    producer = ownership["producer"]
                    break
            value = dict(
                role="operational_log" if parts[0] == "logs" else "run_artifact",
                schema_id="storygen.file/1.0",
                sha256=runtime.sha(path),
                relative_path=relative,
                producer=producer,
                bytes=path.stat().st_size,
            )
            value = dict(artifact_id=runtime.canonical(value), **value)
            contracts.validate("artifact", value)
            artifacts.append(value)
        if rejected:
            errors.append(dict(kind="UNSAFE_OUTPUT", rejected=rejected))
            status = "FAILED"
        started = json.loads((self.root / "RUN_STARTED.json").read_text())
        value = dict(
            schema_version="storygen.central-run/1.0",
            experiment_id=self.manifest["experiment_id"],
            group_id=self.manifest["group_id"],
            protocol_id=self.manifest["protocol_id"],
            protocol_version=self.manifest["protocol_version"],
            run_id=self.lock["run_id"],
            owner_repo="storygen-experiment",
            purpose=self.lock["configuration"]["purpose"],
            scientific_validity="UNVERIFIED",
            execution_status=status,
            contract_status="VALID"
            if status == "COMPLETE" and not errors
            else "INVALID",
            started_utc=started["started_utc"],
            finished_utc=runtime.utc(),
            run_lock_sha256=runtime.sha(self.root / "run.lock.json"),
            runner=self.lock["runner"],
            providers=self.lock["resolved_providers"],
            inputs=self.lock["resolved_inputs"],
            stages=stages,
            artifacts=artifacts,
            errors=errors,
            parent_run_ids=self.lock["configuration"].get("parent_run_ids", []),
            storage=dict(
                raw_backed_up=False,
                metadata_git=True,
                policy="LOCAL_IGNORED_RAW__SANITIZED_GIT_INDEX_ONLY",
            ),
        )
        contracts.validate("run_manifest", value)
        runtime.exclusive_json(self.root / "run_manifest.json", value)
        runtime.exclusive_json(
            self.root / "integrity/SEALED.json",
            dict(
                manifest_sha256=runtime.sha(self.root / "run_manifest.json"),
                run_lock_sha256=value["run_lock_sha256"],
                execution_status=status,
                finished_utc=value["finished_utc"],
            ),
        )
        # Explicit allowlist: never export private config, command arguments, prompts or raw text.
        metadata = {
            k: value[k]
            for k in [
                "experiment_id",
                "group_id",
                "protocol_id",
                "protocol_version",
                "run_id",
                "purpose",
                "scientific_validity",
                "execution_status",
                "contract_status",
                "run_lock_sha256",
            ]
        }
        metadata.update(
            manifest_sha256=runtime.sha(self.root / "run_manifest.json"),
            artifact_index_sha256=runtime.canonical(artifacts),
            artifact_count=len(artifacts),
            error_count=len(errors),
            raw_backed_up=False,
            provider_revisions=[
                {k: r[k] for k in ["repo_id", "commit"]}
                for r in value["providers"]
                if "repo_id" in r and "commit" in r
            ],
            relative_run_root=str(self.root.relative_to(self.depot)),
        )
        path = (
            self.depot
            / "registries/runs"
            / (runtime.canonical(metadata).removeprefix("sha256:") + ".json")
        )
        if not path.exists():
            runtime.exclusive_json(path, metadata)
        return value


def verify(root):
    root = Path(root).resolve()
    p = root / "run_manifest.json"
    seal = json.loads((root / "integrity/SEALED.json").read_text())
    value = contracts.validate("run_manifest", json.loads(p.read_text()))
    if (
        runtime.sha(p) != seal["manifest_sha256"]
        or runtime.sha(root / "run.lock.json") != value["run_lock_sha256"]
        or seal["run_lock_sha256"] != value["run_lock_sha256"]
    ):
        raise RuntimeError("Run manifest/lock seal mismatch")
    listed = set()
    for ref in value["artifacts"]:
        path = contracts.contained(root, ref["relative_path"])
        listed.add(ref["relative_path"])
        if (
            not path.is_file()
            or runtime.sha(path) != ref["sha256"]
            or path.stat().st_size != ref["bytes"]
        ):
            raise RuntimeError("Artifact tampering: " + ref["relative_path"])
        expected = {k: v for k, v in ref.items() if k != "artifact_id"}
        if runtime.canonical(expected) != ref["artifact_id"]:
            raise RuntimeError("Artifact identity mismatch")
    actual = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise RuntimeError("Symlink in sealed run")
        if path.is_file():
            actual.add(str(path.relative_to(root)))
    if actual != listed | {"run_manifest.json", "integrity/SEALED.json"}:
        raise RuntimeError("Unlisted/missing sealed output")
    return dict(
        integrity="VALID",
        execution_status=value["execution_status"],
        scientific_validity=value["scientific_validity"],
        artifacts=len(listed),
        root=str(root),
        raw_backed_up=False,
    )


def status(root):
    root = Path(root)
    if (root / "run_manifest.json").exists():
        return verify(root)
    if not (root / "RUN_STARTED.json").exists():
        return dict(execution_status="NOT_RUN", root=str(root))
    started = json.loads((root / "RUN_STARTED.json").read_text())
    saved = started["owner_process"]
    alive = runtime.identity(saved["pid"]) == saved
    return dict(
        execution_status="RUNNING" if alive else "INTERRUPTED_UNSEALED",
        root=str(root),
        progress=json.loads((root / "progress.json").read_text())
        if (root / "progress.json").is_file()
        else None,
        recovery="Fresh successor with verified parent linkage; never implicitly repeat completed inference",
    )


def recover(root):
    root = Path(root)
    state = status(root)
    if state["execution_status"] == "RUNNING":
        raise RuntimeError("Cannot recover a live owner process")
    if state["execution_status"] != "INTERRUPTED_UNSEALED":
        return state
    lock = json.loads((root / "run.lock.json").read_text())
    depot = root.parents[4]
    store = Store(depot, lock)
    return store.seal(
        "INTERRUPTED",
        [],
        [
            dict(
                kind="OWNER_PROCESS_INTERRUPTED",
                detail="Recorded owner identity is no longer live; partial outputs preserved",
            )
        ],
    )
