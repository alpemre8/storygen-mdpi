"""Offline comparison report: explicit run selection, exact paired populations."""

from pathlib import Path
import csv

from storygen_platform.engine.common import (
    StoryGenError,
    read,
    file_sha,
    identifier,
    digest,
    write_json,
)
from storygen_platform.engine.artifacts import RunStore
from storygen_platform.engine.science_io import science_scope


def generate(root, depot, plan_path, runs, report_id, *, reviewer_analysis=False):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_sg_e01_b_adapter_report", Path(__file__).with_name("adapter.py")
    )
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    io, science = adapter.load("inputs"), adapter.load("science")
    if reviewer_analysis and set(runs) != set(io.PHASES):
        raise StoryGenError("Reviewer analysis requires explicit B1, B2 and B3 run IDs")
    root, depot = Path(root), Path(depot)
    plan = read(plan_path)
    io.validate(plan, depot)
    with science_scope(adapter.roots(root)):
        expected_measurement = adapter.protocol(root).manifest()
    destination = depot / "reports/e01_b" / identifier(report_id)
    if destination.exists():
        raise StoryGenError("Existing E01-B report preserved; choose a new report ID")
    datasets, provenance, sources = {}, {}, {}
    for key, group in plan["groups"].items():
        datasets[(key, "Qwen2.5-7B", "Q4_K_M")] = io.records(
            io.checked(depot, group["baseline_records"])
        )
    datasets[("gemma_cg", "Mistral-7B", "FP16")] = io.records(
        io.checked(depot, plan["fp16"]["records"])
    )
    for phase, run_id in runs.items():
        key = "e01_" + phase.lower() + "_cross_model_precision"
        path = depot / "experiments" / key / "runs" / identifier(run_id)
        lock = read(path / "run.lock.json")
        if (
            lock["lock_sha256"] != digest(lock["identity"])
            or lock["identity"]["experiment_id"] != key
            or lock["identity"]["mode"] != "scientific"
        ):
            raise StoryGenError("E01-B report source run lock mismatch")
        store = RunStore(path)
        store.validate_logs()
        committed = store.committed(lock["lock_sha256"])
        result = committed.get(("measure", "dataset"), {}).get("result")
        if result is None:
            raise StoryGenError("E01-B source stage not committed; finish/resume extraction first")
        source = Path(result["path"])
        sources[phase] = {
            "path": source,
            "artifacts": {
                str((path / ref["relative_path"]).resolve()): ref["sha256"]
                for ref in result["native_artifacts"]
            },
        }
        if not source.resolve().is_relative_to(path.resolve()):
            raise StoryGenError("E01-B source output outside its run")
        for ref in result["native_artifacts"]:
            artifact = path / ref["relative_path"]
            if (
                not artifact.resolve().is_relative_to(path.resolve())
                or file_sha(artifact) != ref["sha256"]
            ):
                raise StoryGenError("E01-B native output hash changed")
        parent = read(source / "PROVENANCE.json")
        if (
            parent["inputs"]["sha256"] != file_sha(plan_path)
            or parent["phase"] != phase
            or parent["measurement"] != expected_measurement
        ):
            raise StoryGenError("E01-B result input manifest/phase mismatch")
        for ref in parent["checkpoint_references"]:
            artifact = Path(ref["path"])
            if (
                not artifact.resolve().is_relative_to(path.resolve())
                or file_sha(artifact) != ref["sha256"]
            ):
                raise StoryGenError("E01-B checkpoint changed since extraction")
        for group_key in io.PHASES[phase]:
            rows = read(source / group_key / "evaluation_task_records.json")
            io.exact_ids(rows, plan["tasks"])
            datasets[(group_key, "Mistral-7B", "Q4_K_M")] = rows
        provenance[phase] = {
            "run_id": run_id,
            "lock_sha256": lock["lock_sha256"],
            "provenance_sha256": file_sha(source / "PROVENANCE.json"),
            "measurement": parent["measurement"],
        }
    with science_scope(adapter.roots(root)):
        table = []
        # Exact user-requested nine combinations, with missing runs left pending.
        combinations = [
            ("qwen_dp", "Qwen2.5-7B", "Q4_K_M"),
            ("qwen_cg", "Qwen2.5-7B", "Q4_K_M"),
            ("qwen_dp", "Mistral-7B", "Q4_K_M"),
            ("qwen_cg", "Mistral-7B", "Q4_K_M"),
            ("gemma_dp", "Qwen2.5-7B", "Q4_K_M"),
            ("gemma_cg", "Qwen2.5-7B", "Q4_K_M"),
            ("gemma_dp", "Mistral-7B", "Q4_K_M"),
            ("gemma_cg", "Mistral-7B", "Q4_K_M"),
            ("gemma_cg", "Mistral-7B", "FP16"),
        ]
        for key, extractor, precision in combinations:
            rows = datasets.get((key, extractor, precision))
            group = plan["groups"][key]
            table.append(
                {
                    "rewrite_model": group["model"],
                    "condition": group["condition"],
                    "extractor": extractor,
                    "precision": precision,
                    "status": "PENDING"
                    if rows is None
                    else (
                        "HISTORICAL"
                        if extractor == "Qwen2.5-7B" or precision == "FP16"
                        else "MEASURED"
                    ),
                    **(
                        science.aggregate(rows)
                        if rows is not None
                        else {
                            k: None
                            for k in (
                                "attempted_n",
                                "measurable_n",
                                "nonmeasurable_n",
                                "TI",
                                "DA",
                                "before_target_distance",
                                "after_target_distance",
                                "mean_gain",
                            )
                        }
                    ),
                }
            )
        contrasts = []
        for key in plan["groups"]:
            for precision in ("Q4_K_M", "FP16"):
                q, m = (key, "Qwen2.5-7B", "Q4_K_M"), (key, "Mistral-7B", precision)
                if m in datasets:
                    contrasts.append(
                        science.paired(
                            datasets[q],
                            datasets[m],
                            plan["tasks"],
                            key + "_M" + precision + "_minus_Q",
                        )
                    )
        q4, f16 = ("gemma_cg", "Mistral-7B", "Q4_K_M"), ("gemma_cg", "Mistral-7B", "FP16")
        if q4 in datasets:
            contrasts.append(
                science.paired(datasets[f16], datasets[q4], plan["tasks"], "gemma_cg_Q4_minus_FP16")
            )
        for model in ("qwen", "gemma"):
            for extractor in ("Qwen2.5-7B", "Mistral-7B"):
                dp, cg = (model + "_dp", extractor, "Q4_K_M"), (model + "_cg", extractor, "Q4_K_M")
                if dp in datasets and cg in datasets:
                    contrasts.append(
                        science.paired(
                            datasets[dp],
                            datasets[cg],
                            plan["tasks"],
                            model + "_" + extractor + "_CG_minus_DP",
                        )
                    )
    supplement = None
    if reviewer_analysis:
        with science_scope(adapter.roots(root)):
            supplement = adapter.load("reviewer").analyze(root, depot, plan, datasets, sources)
    destination.mkdir(parents=True)
    fp16_runtime = read(io.checked(depot, plan["fp16"]["original_manifest"]))["runtime_identity"][
        "server"
    ]
    runtime_note = (
        "The historical FP16 run used context/slot 9216, batch 512, ubatch 128 and 16 GPU layers. "
        "New Q4 uses the original Qwen settings: context/slot 12288, batch 16384, ubatch 2048; GPU offloading remains the same binary's default. "
        "The FP16/Q4 contrast is descriptive and is not an isolated causal precision effect."
    )
    write_json(
        destination / "comparison.json",
        {
            "table": table,
            "paired_comparisons": contrasts,
            "inputs_sha256": file_sha(plan_path),
            "selected_runs": provenance,
            "historical_fp16_runtime": fp16_runtime,
            "precision_comparison_limit": runtime_note,
            "inference_performed": False,
            "scientific_conclusion": "NOT_AUTOMATICALLY_ASSIGNED",
            "bootstrap": "Original E01: 10000 draws, PCG64 seed42, base_interval_id clusters, 95% linear percentile",
            **({"reviewer_analysis": supplement} if supplement is not None else {}),
        },
    )
    with (destination / "comparison.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(table[0]))
        writer.writeheader()
        writer.writerows(table)

    def cell(value):
        return (
            "PENDING"
            if value is None
            else (f"{value:.6f}" if isinstance(value, float) else str(value))
        )

    columns = [
        "rewrite_model",
        "condition",
        "extractor",
        "precision",
        "status",
        "TI",
        "DA",
        "mean_gain",
        "measurable_n",
        "attempted_n",
        "nonmeasurable_n",
        "before_target_distance",
        "after_target_distance",
    ]
    lines = [
        "# E01-B comparison",
        "",
        "TI and DA are fractions (0–1). Gain is Before–Target MAE minus After–Target MAE.",
        "Each row uses its own extractor for Before, Target and After. The table is descriptive; paired contrasts below use only their explicit common eligible task IDs.",
        "",
        runtime_note,
        "",
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join(["---"] * len(columns)) + " |",
    ]
    lines += ["| " + " | ".join(cell(row[c]) for c in columns) + " |" for row in table]
    lines += [
        "",
        "## Paired comparisons",
        "",
        "CI: original E01 base-interval cluster bootstrap, 10,000 resamples, PCG64 seed 42. Each contrast is right minus left; eligibility differences are retained.",
        "",
    ]
    for contrast in contrasts:
        lines += [
            f"### {contrast['contrast']}",
            "",
            f"Matched n={contrast['matched_n']} / {contrast['attempted_n']}; exact task IDs and both extractors' matched means are in comparison.json.",
            "",
        ]
        for metric, estimate in contrast["ci"].items():
            lines.append(
                f"- {metric}: {estimate['point']}; 95% CI {estimate['ci95']}; {estimate['ci_reason'] or 'base-interval clusters'}"
            )
        lines.append("")
    lines += ["## Failures", ""]
    for key, rows in datasets.items():
        failed = [r for r in rows if not r["metric_eligible"]]
        lines.append(
            f"- {' / '.join(key)}: {len(failed)} ineligible of {len(rows)}. Exact reasons are in task_records.json."
        )
    if supplement is not None:
        lines += adapter.load("reviewer").export(destination, supplement, contrasts)
    (destination / "REPORT.md").write_text("\n".join(lines) + "\n")
    write_json(
        destination / "task_records.json", {" / ".join(key): rows for key, rows in datasets.items()}
    )
    return {
        "report": str(destination / "REPORT.md"),
        "rows": len(table),
        "pending": sum(r["status"] == "PENDING" for r in table),
    }
