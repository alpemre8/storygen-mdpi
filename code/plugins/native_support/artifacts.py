"""Portable byte-identical native views over explicit same-run input artifacts."""

from pathlib import Path
import os
import shutil
from storygen_platform.engine.common import file_sha, write_json, StoryGenError


def materialize_owned_views(context):
    root = Path(context.store.root).resolve()
    directory = Path(context.artifact_directory)
    rows = []
    for path in sorted(directory.rglob("*")):
        if not path.is_symlink():
            continue
        target = path.resolve(strict=True)
        if not target.is_relative_to(root / "native") or not target.is_file():
            raise StoryGenError("Native view must reference an explicit same-run native file")
        original = os.readlink(path)
        expected = file_sha(target)
        temporary = path.with_name(path.name + ".materializing")
        if temporary.exists():
            raise StoryGenError("Interrupted native view materialization is preserved")
        shutil.copyfile(target, temporary)
        if file_sha(temporary) != expected:
            raise StoryGenError("Native view changed during materialization")
        os.replace(temporary, path)
        rows.append(
            {
                "path": path.relative_to(root).as_posix(),
                "original_link": original,
                "same_run_target": target.relative_to(root).as_posix(),
                "sha256": expected,
                "bytes": path.stat().st_size,
            }
        )
    if rows:
        write_json(
            directory / "MATERIALIZED_NATIVE_VIEWS.json",
            {"version": "same-run-native-views/1", "views": rows},
        )
    return rows
