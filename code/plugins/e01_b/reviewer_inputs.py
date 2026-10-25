"""Receipt-bound scene scores for offline E01-B analysis; no input rewriting."""

from pathlib import Path

from storygen_platform.engine.common import StoryGenError, read, file_sha
from storygen_platform.historical import HistoricalCatalog, restricted


class Reader:
    def __init__(self, root, depot, io):
        self.depot = Path(depot).resolve()
        self.io = io
        self.locations = io.module(root, "native_support/locations.py").Locations(root, depot)
        self.catalog = HistoricalCatalog(depot)
        self.receipts = {}
        self.inputs = {}

    def historical(self, recorded, expected=None):
        path = Path(self.locations.relocate(str(recorded))).resolve()
        if not path.is_relative_to(self.depot) or restricted(path):
            raise StoryGenError("Reviewer input outside open depot")
        relative = path.relative_to(self.depot).as_posix()
        candidates = sorted(
            (
                r
                for r in self.catalog.index["runs"]
                if path.is_relative_to(self.depot / r["active_resolved_root"])
            ),
            key=lambda r: (-len(r["active_resolved_root"]), r["run_id"]),
        )
        for row in candidates:
            run_id = row["run_id"]
            if run_id not in self.receipts:
                receipt = self.catalog.select(run_id)
                self.receipts[run_id] = {
                    a["relative_path"]: a
                    for a in receipt["artifacts"]
                    if not a.get("sealed") and a.get("access") != "sealed"
                }
            artifact = self.receipts[run_id].get(relative)
            if artifact is None:
                continue
            if row["qualification"] == "ENGINEERING_OR_TEST":
                raise StoryGenError("Engineering input cannot supply reviewer scores")
            sha = artifact["sha256"]
            if expected is not None and sha != expected.removeprefix("sha256:"):
                raise StoryGenError("Reviewer manifest lineage/hash mismatch: " + relative)
            ref = {"path": relative, "sha256": sha}
            self.io.checked(self.depot, ref)
            self.inputs[relative] = {
                **ref,
                "historical_run_id": run_id,
                "receipt_sha256": row["receipt_sha256"],
            }
            return read(path)
        raise StoryGenError("Reviewer input lacks imported receipt: " + relative)

    def native(self, path, source):
        path = Path(path).resolve()
        if not path.is_relative_to(Path(source["path"]).resolve()):
            raise StoryGenError("Reviewer native input outside selected phase")
        expected = source["artifacts"].get(str(path))
        if expected is None or not path.is_file() or file_sha(path) != expected:
            raise StoryGenError("Reviewer native score missing/changed: " + str(path))
        relative = path.relative_to(self.depot).as_posix()
        self.inputs[relative] = {"path": relative, "sha256": expected, "origin": "SELECTED_RUN"}
        return read(path)


def index_rows(rows, expected_ids, protocol, film=None):
    """Keep failed score rows, but reject identity loss or instrument mixing."""
    result = {}
    for row in rows:
        sid = row["scene_id"]
        if sid in result or sid not in expected_ids:
            raise StoryGenError("Duplicate or unexpected reviewer scene identity: " + sid)
        if row.get("measurement_protocol_hash", protocol) != protocol:
            raise StoryGenError("Reviewer scene instrument/phase mismatch")
        if film is not None and row.get("film_id", film) != film:
            raise StoryGenError("Reviewer scene film identity mismatch")
        result[sid] = row
    if set(result) != set(expected_ids):
        raise StoryGenError("Missing reviewer scene identities")
    return result


def phase_manifest(reader, source, phase):
    directory = Path(source["path"])
    manifest = reader.native(directory / "originals/feature_set_manifest.json", source)
    provenance = reader.native(directory / "PROVENANCE.json", source)
    if provenance["phase"] != phase or manifest["measurement"] != provenance["measurement"]:
        raise StoryGenError("Reviewer original phase instrument mismatch")
    return manifest


def load(root, depot, plan, sources, io):
    reader = Reader(root, depot, io)
    q_protocol = read(io.checked(depot, plan["reference"]))["measurement"]["protocol_hash"]
    needed = {}
    for task in plan["tasks"]:
        for side in ("source", "reference"):
            needed.setdefault(task[side + "_film_id"], set()).update(task[side + "_scene_ids"])
    q_original = {}
    reference_root = Path(depot) / plan["reference"]["path"]
    reader.historical(reference_root, plan["reference"]["sha256"])
    for film, ids in sorted(needed.items()):
        rows = reader.historical(reference_root.parent / "films" / film / "scene_features_llm.json")
        # The historical feature set also contains scenes outside the experiment.
        all_ids = [r["scene_id"] for r in rows]
        if len(set(all_ids)) != len(all_ids) or not ids <= set(all_ids):
            raise StoryGenError("Original Qwen scene population mismatch")
        indexed = index_rows([r for r in rows if r["scene_id"] in ids], ids, q_protocol, film)
        q_original.update({(film, sid): r for sid, r in indexed.items()})

    q_after = {}
    for key, group in plan["groups"].items():
        baseline = read(io.checked(depot, group["baseline_manifest"]))
        reanalysis = baseline["reanalysis_run"]
        directory = Path(reader.locations.relocate(reanalysis["path"]))
        manifest = reader.historical(
            directory / "reanalysis_manifest.json", reanalysis["manifest_sha256"]
        )
        if (
            manifest["measurement"]["protocol_hash"] != q_protocol
            or manifest["source_rewrite_run"]["manifest_sha256"].removeprefix("sha256:")
            != group["rewrite_manifest"]["sha256"]
            or manifest["source_feature_set_manifest"]["sha256"].removeprefix("sha256:")
            != plan["reference"]["sha256"]
        ):
            raise StoryGenError("Reviewer Qwen reanalysis model/condition lineage mismatch")
        failed = {f["task_id"] for f in manifest["failures"]}
        q_after[key] = {}
        for task in plan["tasks"]:
            tid = task["task_id"]
            path = directory / "tasks" / tid / "rewritten_scene_features.json"
            if not path.is_file() and tid in failed:
                q_after[key][tid] = {}
                continue
            rows = reader.historical(path)
            q_after[key][tid] = index_rows(
                rows, task["source_scene_ids"], q_protocol, task["source_film_id"]
            )

    original, after, protocols = {}, {}, {}
    for phase, source in sources.items():
        directory = Path(source["path"])
        manifest = phase_manifest(reader, source, phase)
        protocol = manifest["measurement"]["protocol_hash"]
        protocols[phase] = protocol
        original[phase] = {}
        for film, ids in sorted(needed.items()):
            rows = reader.native(directory / "originals" / film / "scene_features_llm.json", source)
            indexed = index_rows(rows, ids, protocol, film)
            original[phase].update({(film, sid): r for sid, r in indexed.items()})
        for key in io.PHASES[phase]:
            group_manifest = reader.native(directory / key / "feature_set_manifest.json", source)
            if (
                group_manifest["measurement"] != manifest["measurement"]
                or group_manifest["source"]["rewrite_manifest"]
                != plan["groups"][key]["rewrite_manifest"]
            ):
                raise StoryGenError("Reviewer rewritten phase/model/condition mismatch")
            after[key] = {}
            for task in plan["tasks"]:
                tid = task["task_id"]
                if tid in plan["groups"][key]["missing_rewrites"]:
                    after[key][tid] = {}
                    continue
                rows = reader.native(
                    directory / key / "tasks" / tid / "rewritten_scene_features.json", source
                )
                after[key][tid] = index_rows(
                    rows, task["source_scene_ids"], protocol, task["source_film_id"]
                )
    return {
        "q_original": q_original,
        "q_after": q_after,
        "original": original,
        "after": after,
        "protocols": protocols,
        "inputs": sorted(reader.inputs.values(), key=lambda r: r["path"]),
    }
