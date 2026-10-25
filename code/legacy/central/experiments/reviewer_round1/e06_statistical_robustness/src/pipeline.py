"""Create-only deterministic runs, progress and scientific validation gates."""

from datetime import datetime, timezone
from pathlib import Path
import ast
import json
import os
import time
import sys
from common import MODULES, csv_write, read, write
from analyses import ANALYSES, NAMES, validate
from reporting import COVERAGE, RESULT_JSON, markdown_table, report, seal_inputs


def clock_text(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"


class Progress:
    def __init__(self, root):
        self.root = Path(root)
        self.start = time.monotonic()
        self.stage_start = self.start
        self.stage = None
        self.errors = []
        self.last = {}

    def __call__(self, stage, module, completed, total, status="RUNNING"):
        now = time.monotonic()
        if (stage, module) != self.stage:
            self.stage = (stage, module)
            self.stage_start = now
        elapsed = now - self.start
        duration = now - self.stage_start
        eta = (
            duration * (total - completed) / completed
            if completed >= 3 and duration >= 0.5
            else None
        )
        value = dict(
            stage=stage,
            module=module,
            completed_units=completed,
            total_units=total,
            progress_pct=100 * completed / total if total else 0,
            elapsed=clock_text(elapsed),
            ETA=clock_text(eta) if eta is not None else None,
            status=status,
            errors=self.errors,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        temporary = self.root / "08_logs/.progress.tmp"
        write(temporary, value)
        os.replace(temporary, self.root / "08_logs/PROGRESS.json")
        with (self.root / "08_logs/events.jsonl").open("a") as stream:
            stream.write(json.dumps(value, sort_keys=True) + "\n")
        if completed in (1, total) or completed % 25 == 0:
            print(
                f"[{status}] {stage}/{module} {completed}/{total} {value['progress_pct']:.1f}% elapsed={value['elapsed']} ETA={value['ETA'] or 'unavailable'}",
                flush=True,
            )
        self.last = value


def prepare(root, kind, binding=None):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=False)
    for name in (
        "00_manifest",
        "01_preflight",
        "02_canonical_metrics",
        "03_analyses",
        "04_cross_validation",
        "05_tables",
        "06_figures",
        "08_logs",
    ):
        (root / name).mkdir()
    home = Path(__file__).resolve().parents[1]
    lock_path = home / "dependencies.lock.yaml"
    implementation = dict(
        python=sys.version, provider_sources=read(home / "provider_sources.json")
    )
    if lock_path.is_file():
        implementation["source_lock"] = read(lock_path)
    write(root / "00_manifest/IMPLEMENTATION_IDENTITY.json", implementation)
    write(
        root / "E06_MANIFEST.json",
        dict(
            protocol="E06_V1",
            dataset_kind=kind,
            created_at=datetime.now(timezone.utc).isoformat(),
            binding=str(binding) if binding else None,
            inference_requests=0,
            scientific_validity="SCIENTIFIC_RESULTS_NOT_YET_VERIFIED",
        ),
    )
    write(
        root / "E06_STATUS.json",
        dict(
            status="RUNNING",
            dataset_kind=kind,
            modules={a: "PENDING" for a in MODULES},
            scientific_validity="SCIENTIFIC_RESULTS_NOT_YET_VERIFIED",
        ),
    )
    return root


def write_module(root, a, result):
    directory = root / "03_analyses" / a
    write(directory / RESULT_JSON[a], result)
    for filename, rows in result["tables"].items():
        csv_write(directory / filename, rows)
    (directory / (a + "_SUMMARY.md")).write_text(
        "# "
        + a
        + " — "
        + NAMES[a]
        + "\n\nStatus: "
        + result["status"]
        + "\n\n"
        + result["denominator"]
        + "\n\n"
        + (result.get("limitation", ""))
        + "\n\n"
        + "\n".join(
            f"- {name}: {len(rows)} rows" for name, rows in result["tables"].items()
        )
        + "\n"
    )


def offline_dependency_check():
    """Actual import/source audit, recorded as evidence for V14."""
    import sys

    forbidden = {
        "requests",
        "httpx",
        "openai",
        "transformers",
        "torch",
        "llama_cpp",
        "vllm",
    }
    imported = sorted(name for name in sys.modules if name.split(".")[0] in forbidden)
    code_imports = []
    import storygen_evaluation.metrics as canonical_metrics

    paths = sorted(Path(__file__).parent.glob("*.py"))
    provider = Path(canonical_metrics.__file__).parent
    paths += [
        provider / name
        for name in ("__init__.py", "metrics.py", "io.py", "provenance.py")
    ]
    for p in paths:
        for node in ast.walk(ast.parse(p.read_text())):
            names = (
                [n.name.split(".")[0] for n in node.names]
                if isinstance(node, ast.Import)
                else [str(node.module).split(".")[0]]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            code_imports.extend(n for n in names if n in forbidden)
    return dict(
        status="PASS" if not code_imports else "FAIL",
        ambient_process_modules=imported,
        scope="Owned E06 and pinned canonical dependency source imports; unrelated preloaded host/test modules are not E06 dependencies",
        audited_files=[str(p) for p in paths],
        source_imports=code_imports,
    )


def execute(root, dataset, progress, inputs=None, inventory=None, compile_pdf=False):
    root = Path(root)
    write(
        root / "01_preflight/INVENTORY.json",
        inventory or {"status": "SYNTHETIC_FIXTURE_ONLY"},
    )
    write(root / "E06_PROVENANCE.json", dataset.provenance)
    canonical = [
        {
            k: r[k]
            for k in (
                "task_id",
                "base_interval_id",
                "screenplay_id",
                "feature",
                "model",
                "condition",
                "eligible",
                "TI",
                "DA",
                "dB",
                "dA",
                "G",
                "failure_classification",
            )
        }
        for m in dataset.models
        for c in ("DP-v1", "CG-v1")
        for r in dataset.rows(m, c)
    ]
    csv_write(root / "02_canonical_metrics/CANONICAL_TASK_METRICS.csv", canonical)
    write(root / "02_canonical_metrics/COMPATIBILITY.json", dataset.validation)
    results = {}
    for i, (a, fn) in enumerate(ANALYSES.items(), 1):
        progress("analysis", a, 0, 1)
        result = fn(dataset)
        write_module(root, a, result)
        results[a] = result
        progress("analysis", a, 1, 1, result["status"])
        write(
            root / "E06_STATUS.json",
            dict(
                status="RUNNING",
                dataset_kind=dataset.kind,
                modules={
                    name: results[name]["status"] if name in results else "PENDING"
                    for name in MODULES
                },
                scientific_validity="SCIENTIFIC_RESULTS_NOT_YET_VERIFIED",
            ),
        )
    progress("validation", "V01-V15", 0, 1)
    validation = validate(dataset, results, inputs.unchanged() if inputs else True)
    dependency = offline_dependency_check()
    validation["checks"]["V14"] = dict(status=dependency["status"], detail=dependency)
    # V13 verifies each CSV against an independent serialization of persisted JSON.
    import csv

    consistent = True
    for a in MODULES:
        persisted = read(root / "03_analyses" / a / RESULT_JSON[a])
        for filename, rows in persisted["tables"].items():
            with (root / "03_analyses" / a / filename).open(newline="") as stream:
                exported = list(csv.DictReader(stream))
            expected = [
                {
                    k: json.dumps(v, sort_keys=True)
                    if isinstance(v, (dict, list))
                    else ""
                    if v is None
                    else str(v)
                    for k, v in row.items()
                }
                for row in rows
            ]
            consistent &= exported == expected
    validation["checks"]["V13"] = dict(
        status="PASS" if consistent else "FAIL",
        detail="Persisted JSON/CSV cell and ordering agreement; report reads these sealed files",
    )
    validation["status"] = (
        "PASS"
        if all(v["status"] == "PASS" for v in validation["checks"].values())
        else "FAIL"
    )
    write(root / "E06_VALIDATION.json", validation)
    write(root / "04_cross_validation/E06_VALIDATION.json", validation)
    summary = dict(
        dataset_kind=dataset.kind,
        modules={a: r["status"] for a, r in results.items()},
        validation=validation["status"],
        planned_tasks=len(dataset.tasks),
        planned_observations=len(canonical),
        valid_observations=sum(r["eligible"] for r in canonical),
        global_common_tasks=len(dataset.common()),
        scientific_validity="SCIENTIFIC_RESULTS_NOT_YET_VERIFIED",
    )
    write(root / "E06_RESULTS_SUMMARY.json", summary)
    summary_rows = [
        dict(module=a, status=r["status"], tables=len(r["tables"]))
        for a, r in results.items()
    ]
    (root / "E06_RESULTS_SUMMARY.md").write_text(
        "# E06 "
        + dataset.kind
        + "\n\n"
        + markdown_table(summary_rows, ["module", "status", "tables"])
        + "\nScientific results require independent validation.\n"
    )
    for a, result in results.items():
        for name, rows in result["tables"].items():
            # Every reported table comes directly from a computed result.
            (root / "05_tables" / name.replace(".csv", ".md")).write_text(
                markdown_table(rows, list(rows[0]))
                if rows
                else "No eligible rows; see module status.\n"
            )
    (root / "06_figures/README.md").write_text(
        "No figures required: complete computed tables retained. No fabricated graphics.\n"
    )
    (root / "E06_REVIEWER_COVERAGE.md").write_text(COVERAGE)
    write(
        root / "00_manifest/RESULT_SEAL.json",
        dict(dataset_kind=dataset.kind, files=seal_inputs(root)),
    )
    status = (
        "COMPLETE" if validation["status"] == "PASS" else "SCIENTIFIC_VALIDATION_FAILED"
    )
    write(root / "E06_STATUS.json", dict(status=status, **summary))
    if status == "COMPLETE":
        report(root, compile_pdf=compile_pdf, fixture=dataset.kind == "SYNTHETIC")
    else:
        (root / "07_report").mkdir()
        (root / "07_report/REPORT_BLOCKED.md").write_text(
            "Scientific report blocked: inspect E06_VALIDATION.json. No successful results are fabricated.\n"
        )
    progress("packaging", "E06", 1, 1, status)
    return dict(status=status, output=str(root))


def run(root, binding=None, synthetic=False, compile_pdf=False):
    root = prepare(root, "SYNTHETIC" if synthetic else "REAL", binding)
    progress = Progress(root)
    try:
        if synthetic:
            from fixtures import fixture

            ds = fixture()
            inputs = None
            inventory = None
        else:
            from loader import load

            ds, inputs, inventory = load(binding, progress)
            if ds.kind != "REAL":
                raise ValueError(
                    "Real run cannot consume a synthetic historical binding"
                )
        return execute(root, ds, progress, inputs, inventory, compile_pdf)
    except BaseException as exc:
        # Preserve partial run; never overwrite or silently resume it.
        status = (
            "INTERRUPTED"
            if isinstance(exc, (KeyboardInterrupt, SystemExit))
            else "FAILED"
        )
        prior = read(root / "E06_STATUS.json")
        prior.update(status=status, error_type=type(exc).__name__)
        # Exception text could contain screenplay content from third-party readers.
        # Preserve only exception type and safe stage metadata in public artifacts.
        write(root / "E06_STATUS.json", prior)
        progress.errors.append(type(exc).__name__)
        progress("failure", "E06", 0, 1, status)
        raise
