"""Explicit physical locations for immutable historical artifacts; no scientific conversion."""

from pathlib import Path
import json
from storygen_platform.engine.common import StoryGenError, file_sha


class Locations:
    def __init__(self, code_root, depot_root, *, owned_roots=()):
        self.code = Path(code_root).resolve()
        self.depot = Path(depot_root).resolve()
        self.owned_roots = tuple(Path(root).resolve() for root in owned_roots)
        self.roots = {
            "storygen-rewrite": self.code / "plugins/rewrite/historical",
            "storygen-feature-extraction": self.code / "plugins/feature_extraction/historical",
            "storygen-evaluation": self.code / "plugins/evaluation/historical",
            "storygen-naturalness": self.code / "plugins/naturalness/historical",
            "storygen-experiment": self.code / "legacy/central",
        }
        self.roots.update(
            {
                name + "-depot": self.depot / "migration/sources" / (name + "-depot")
                for name in list(self.roots)
            }
        )
        self.external = {}
        manifest = self.depot / "migration/corrective-external-inputs/manifest.json"
        if manifest.is_file():
            for item in json.loads(manifest.read_text()):
                path = (self.depot / item["path"]).resolve()
                if not path.is_relative_to(self.depot) or file_sha(path) != item["sha256"]:
                    raise StoryGenError("Historical external input changed")
                self.external[item["recorded_path"]] = str(path)

    def relocate(self, recorded):
        current = Path(recorded)
        if current.is_absolute() and any(
            current.resolve().is_relative_to(root) for root in self.owned_roots
        ):
            return str(recorded)
        if str(recorded) in self.external:
            return self.external[str(recorded)]
        parts = Path(recorded).parts
        common = next(
            (p for p in ("story_generation_blocks_versions", "story_generation") if p in parts),
            None,
        )
        if common:
            index = parts.index(common)
            suffix = parts[index + 1 :]
            if suffix and suffix[0] == "02-rewriteV1.3":
                root = self.roots["storygen-rewrite"] / "rewrite"
                path = root.joinpath(*suffix[1:]).resolve()
                if not path.is_relative_to(root.resolve()):
                    raise StoryGenError("Historical code locator escapes its preserved owner")
                return str(path)
            routes = {
                "_inputs": self.roots["storygen-feature-extraction-depot"],
                "_contracts": self.roots["storygen-feature-extraction-depot"]
                / "history/legacy-common-depot",
                "01-feature_extraction": self.roots["storygen-feature-extraction-depot"]
                / "history/legacy-common-depot",
                "03-reanalysis": self.roots["storygen-feature-extraction-depot"]
                / "history/legacy-common-depot",
                "01b-taskset": self.roots["storygen-rewrite-depot"],
                "02-rewrite": self.roots["storygen-rewrite-depot"],
                "04-evaluation": self.roots["storygen-evaluation-depot"],
            }
            if len(suffix) >= 2 and suffix[0] == "runs" and suffix[1] in routes:
                return str(routes[suffix[1]].joinpath(*suffix))
        matches = [(i, self.roots[p]) for i, p in enumerate(parts) if p in self.roots]
        if not matches:
            path = Path(recorded)
            if path.is_absolute() and not any(
                path.resolve().is_relative_to(base) for base in (self.code, self.depot)
            ):
                raise StoryGenError(
                    "Historical artifact requires an explicit preserved location: " + str(recorded)
                )
            return str(recorded)
        if len(matches) != 1:
            raise StoryGenError("Ambiguous historical artifact owner")
        position, root = matches[0]
        path = root.joinpath(*parts[position + 1 :]).resolve()
        if not path.is_relative_to(root.resolve()):
            raise StoryGenError("Historical reference escapes preserved owner")
        return str(path)
