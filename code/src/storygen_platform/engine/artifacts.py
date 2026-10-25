"""Durable hash-chained JSONL records. Events, rather than caches, are authoritative."""

from contextlib import contextmanager
from pathlib import Path
import fcntl
import json
import os
import shutil
import uuid
from .common import (
    StoryGenError,
    canonical,
    digest,
    utc,
    contained,
    file_sha,
    ensure_directory,
    sync_directory,
    read,
)


class CorruptLog(StoryGenError):
    pass


class Journal:
    def __init__(self, path):
        self.path = Path(path)
        ensure_directory(self.path.parent)
        self._append_cursor = None

    @staticmethod
    def _signature(stream):
        value = os.fstat(stream.fileno())
        return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)

    def scan(self, *, _locked=False):
        if not self.path.exists():
            return []
        records = []
        previous = None
        with self.path.open("rb") as stream:
            if not _locked:
                fcntl.flock(stream.fileno(), fcntl.LOCK_SH)
            for line_number, line in enumerate(stream, 1):
                try:
                    if not line.endswith(b"\n"):
                        raise ValueError("torn trailing write")
                    envelope = json.loads(line)
                    record = envelope["record"]
                    if envelope["sha256"] != digest(record):
                        raise ValueError("record checksum mismatch")
                    if record["previous"] != previous or record["sequence"] != len(records):
                        raise ValueError("hash chain or sequence mismatch")
                    previous = envelope["sha256"]
                    records.append(record)
                except (ValueError, KeyError, TypeError) as exc:
                    raise CorruptLog(
                        f"{self.path}:{line_number}: {exc}; preserve and quarantine before resume"
                    ) from exc
        return records

    def append(self, kind, **data):
        if {"sequence", "previous", "utc"} & set(data):
            raise StoryGenError("Journal envelope fields cannot be overridden")
        created = not self.path.exists()
        with self.path.open("a+b") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            signature = self._signature(stream)
            if self._append_cursor is not None and self._append_cursor[0] == signature:
                _, sequence, previous = self._append_cursor
            else:
                records = self.scan(_locked=True)
                sequence = len(records)
                previous = digest(records[-1]) if records else None
            record = {
                "kind": kind,
                "utc": utc(),
                "sequence": sequence,
                "previous": previous,
                **data,
            }
            stream.write(canonical({"record": record, "sha256": digest(record)}) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
            # This is only an append optimization under the exclusive file lock.
            # Any external size/inode/time change forces complete verification;
            # scan() and recovery always verify the authoritative JSONL afresh.
            self._append_cursor = (self._signature(stream), sequence + 1, digest(record))
        if created:
            sync_directory(self.path.parent)
        return record

    def quarantine_tail(self):
        """Explicit recovery keeps the complete original log before replacing its valid prefix."""
        backup = self.path.with_name(self.path.name + ".quarantine-" + uuid.uuid4().hex)
        with self.path.open("a+b") as guard:
            fcntl.flock(guard.fileno(), fcntl.LOCK_EX)
            shutil.copyfile(self.path, backup)
            with backup.open("rb") as stream:
                os.fsync(stream.fileno())
            sync_directory(backup.parent)
            good = []
            previous = None
            for line in backup.read_bytes().splitlines(keepends=True):
                try:
                    value = json.loads(line)
                    record = value["record"]
                    if not line.endswith(b"\n") or value["sha256"] != digest(record):
                        break
                    if record["sequence"] != len(good) or record["previous"] != previous:
                        break
                    previous = value["sha256"]
                    good.append(line)
                except (ValueError, KeyError, TypeError):
                    break
            guard.seek(0)
            guard.truncate()
            guard.write(b"".join(good))
            guard.flush()
            os.fsync(guard.fileno())
        self.append(
            "RECOVERY_DECISION",
            quarantine=backup.name,
            quarantine_sha256=file_sha(backup),
            action="retained valid prefix; full original preserved",
        )
        return backup


class RunStore:
    def __init__(self, root):
        self.root = Path(root)
        self.events = Journal(self.root / "events.jsonl")
        self._journals = {}

    @contextmanager
    def writer(self):
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / ".writer.lock").open("a+b") as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise StoryGenError("Run already has a foreground writer") from exc
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def data(self, stage, kind, unit_id, attempt_id, value):
        path = contained(self.root, f"stages/{stage}/{kind}.jsonl")
        journal = self._journals.get(path)
        if journal is None:
            journal = self._journals.setdefault(path, Journal(path))
        record = journal.append(kind.upper(), unit_id=unit_id, attempt_id=attempt_id, value=value)
        return {
            "path": path.relative_to(self.root).as_posix(),
            "sequence": record["sequence"],
            "sha256": digest(record),
        }

    def committed(self, lock_hash):
        accepted = {}
        output_events = {}
        verified_journals = {}

        def verified(path):
            if path not in verified_journals:
                verified_journals[path] = Journal(contained(self.root, path)).scan()
            return verified_journals[path]

        for event in self.events.scan():
            if event.get("lock_hash", lock_hash) != lock_hash:
                raise CorruptLog("Event belongs to a different scientific/run lock")
            key = (event.get("stage_id"), event.get("unit_id"))
            if event["kind"] in {"INPUT_PERSISTED", "RAW_PERSISTED", "OUTPUT_PERSISTED"}:
                ref = event["reference"]
                category = {
                    "INPUT_PERSISTED": "inputs",
                    "RAW_PERSISTED": "raw",
                    "OUTPUT_PERSISTED": "outputs",
                }[event["kind"]]
                if ref["path"] != f"stages/{key[0]}/{category}.jsonl":
                    raise CorruptLog("Cross-stage artifact provenance misbinding")
                records = verified(ref["path"])
                if (
                    ref["sequence"] >= len(records)
                    or digest(records[ref["sequence"]]) != ref["sha256"]
                ):
                    raise CorruptLog(
                        f"Durable input/raw/output reference missing or changed: {key}"
                    )
                record = records[ref["sequence"]]
                if record["unit_id"] != key[1] or record["attempt_id"] != event["attempt_id"]:
                    raise CorruptLog("Attempt artifact provenance misbinding")
            if event["kind"] == "OUTPUT_PERSISTED":
                output_events[key, event["attempt_id"]] = event["reference"]
            if event["kind"] != "COMMITTED":
                continue
            if key in accepted:
                raise CorruptLog(f"Duplicate/conflicting commit for {key}")
            reference = event["reference"]
            if output_events.get((key, event["attempt_id"])) != reference:
                raise CorruptLog(f"Commit before durable output event: {key}")
            data = verified(reference["path"])
            index = reference["sequence"]
            if index >= len(data) or digest(data[index]) != reference["sha256"]:
                raise CorruptLog(f"Committed output missing or changed: {key}")
            record = data[index]
            if record["unit_id"] != key[1] or record["attempt_id"] != event["attempt_id"]:
                raise CorruptLog("Commit provenance misbinding")

            def validate_native(value):
                if isinstance(value, dict):
                    for ref in value.get("native_artifacts", []):
                        path = contained(self.root, ref["relative_path"])
                        if (
                            not ref["relative_path"].startswith("native/")
                            or not path.is_file()
                            or path.is_symlink()
                            or file_sha(path) != ref["sha256"]
                            or path.stat().st_size != ref["bytes"]
                        ):
                            raise CorruptLog(
                                "Native scientific output missing or changed: "
                                + ref["relative_path"]
                            )
                    for child in value.values():
                        validate_native(child)
                elif isinstance(value, list):
                    for child in value:
                        validate_native(child)

            validate_native(record["value"])
            accepted[key] = record["value"]
        return accepted

    def validate_logs(self):
        lock_path = self.root / "run.lock.json"
        if lock_path.exists():
            identity = read(lock_path)["identity"]
            protocol = identity["protocol"]
            if identity.get("historical_sources"):
                from ..historical import HistoricalCatalog

                depot = self.root.parents[3]
                catalog = HistoricalCatalog(depot)
                for pinned in identity.get("historical_provenance", {}).values():
                    if catalog.runs[pinned["run_id"]]["receipt_sha256"] != pinned["receipt_sha256"]:
                        raise CorruptLog(
                            "Historical source receipt differs from immutable input lock"
                        )
                    ref = catalog.artifact(pinned["run_id"], pinned["artifact_path"])
                    if ref.sha256 != pinned["artifact_sha256"]:
                        raise CorruptLog("Historical source differs from immutable input hash")
                for selected in set(identity["historical_sources"].values()):
                    run_id, relative = selected.split("@", 1)
                    catalog.artifact(run_id, relative)
                    catalog.verify(run_id)
            snapshots = [
                (self.root / "snapshot" / name, expected)
                for name, expected in protocol["files"].items()
            ]
            snapshots += [
                (
                    self.root / "snapshot/instruments" / f"{i}-{Path(item['path']).name}",
                    item["sha256"],
                )
                for i, item in enumerate(protocol["instruments"])
                if item.get("snapshot", True)
            ]
            for path, expected in snapshots:
                if not path.is_file() or file_sha(path) != expected:
                    raise CorruptLog("Immutable run snapshot missing or changed: " + str(path))
        self.events.scan()
        for path in self.root.glob("stages/*/*.jsonl"):
            Journal(path).scan()
