from __future__ import annotations

import csv
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .io import read_json, sha256_file, write_csv, write_json

BLOCK_VERSION = "2.4.1"
BUNDLE_CONTRACT_ID = "storygen.paper-ready-bundle"
BUNDLE_CONTRACT_VERSION = "2.4"

FEATURE_DISPLAY = {
    "pacing": "Pacing",
    "dialogue_density": "Dialogue density",
    "action_density": "Action density",
    "character_interaction": "Character interaction",
    "character_interaction_density": "Character interaction",
    "emotion_intensity": "Emotion intensity",
}
TABLE8_FEATURE_ORDER = ["pacing", "emotion_intensity", "dialogue_density", "action_density", "character_interaction"]
TABLE10_FEATURE_ORDER = ["pacing", "dialogue_density", "action_density", "character_interaction", "emotion_intensity"]
INTERVAL_ORDER = ["short", "medium", "long"]
INTERVAL_DISPLAY = {"short": "Short (5 scenes)", "medium": "Medium (8 scenes)", "long": "Long (12 scenes)"}
EXPECTED_TABLE_FILES = {
    "table6_global_common.csv", "table6_global_common.tex",
    "table7_within_model_paired.csv", "table7_within_model_paired.tex",
    "table8_primary_by_feature.csv", "table8_primary_by_feature.tex",
    "table9_primary_by_length.csv", "table9_primary_by_length.tex",
    "table10_extractor_repeatability.csv", "table10_extractor_repeatability.tex",
}
EXPECTED_PROVENANCE_FILES = {
    "SOURCE_ARTIFACTS.json",
    "GLOBAL_COMMON_TASK_IDS.json",
    "REFERENCE_BASELINE.json",
    "EXTRACTOR_REPEATABILITY_SUMMARY.json",
}



def _resolve(project_root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (project_root / path).resolve()


def _check(checks: list[dict], name: str, condition: bool, detail: str = "", critical: bool = True) -> None:
    checks.append({"check": name, "status": "PASS" if condition else "FAIL", "critical": critical, "detail": detail})


def _fmt_float(value: Any, digits: int = 4) -> str:
    if value is None:
        return "--"
    return f"{float(value):.{digits}f}"


def _fmt_percent(value: Any, digits: int = 2) -> str:
    if value is None:
        return "--"
    return f"{100.0 * float(value):.{digits}f}%"


def _latex_escape(value: Any) -> str:
    text = str(value if value is not None else "--")
    for old, new in (("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"), ("_", r"\_"), ("#", r"\#")):
        text = text.replace(old, new)
    return text


def _write_latex_table(path: Path, rows: list[dict[str, Any]], columns: list[tuple[str, str]], caption: str, label: str) -> None:
    aligns = "l" + "r" * (len(columns) - 1)
    lines = [
        r"\begin{table}[htbp]",
        r"\centering",
        f"\\caption{{{_latex_escape(caption)}}}",
        f"\\label{{{label}}}",
        f"\\begin{{tabular}}{{{aligns}}}",
        r"\toprule",
        " & ".join(_latex_escape(title) for _, title in columns) + r" \\",
        r"\midrule",
    ]
    for row in rows:
        lines.append(" & ".join(_latex_escape(row.get(key)) for key, _ in columns) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular}", r"\end{table}", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_table_pair(base: Path, stem: str, rows: list[dict[str, Any]], columns: list[tuple[str, str]], caption: str) -> None:
    ordered = [{key: row.get(key) for key, _ in columns} for row in rows]
    write_csv(base / "tables" / f"{stem}.csv", ordered, [key for key, _ in columns])
    _write_latex_table(base / "tables" / f"{stem}.tex", ordered, columns, caption, f"tab:{stem}")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _to_number(value: Any) -> Any:
    if value is None or isinstance(value, (int, float, bool)):
        return value
    text = str(value).strip()
    if text == "":
        return None
    if text.lower() in {"true", "false"}:
        return text.lower() == "true"
    try:
        return float(text) if any(char in text.lower() for char in (".", "e")) else int(text)
    except ValueError:
        return value


def _typed_csv(path: Path) -> list[dict[str, Any]]:
    return [{key: _to_number(value) for key, value in row.items()} for row in _read_csv(path)]


def _canonical_feature(value: Any) -> str:
    text = str(value or "").strip()
    aliases = {
        "llm_pacing_score": "pacing",
        "llm_dialogue_density_score": "dialogue_density",
        "llm_action_density_score": "action_density",
        "llm_character_interaction_score": "character_interaction",
        "llm_character_interaction_density_score": "character_interaction",
        "llm_emotion_intensity_score": "emotion_intensity",
        "character_interaction_density": "character_interaction",
    }
    return aliases.get(text, text)


def _identity_matches(expected: dict[str, Any], actual_measurement: dict[str, Any]) -> bool:
    actual = {key: actual_measurement.get(key) for key in (
        "measurement_protocol_id", "measurement_protocol_version", "protocol_hash", "instrument_hash",
        "prompt_hash", "schema_hash", "system_instruction_hash", "request_contract_hash", "decoding_hash",
    )}
    actual["model_sha256"] = (actual_measurement.get("model") or {}).get("model_sha256")
    return expected == actual


def _reference_baseline(condition_rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not condition_rows:
        return {"status": "unavailable"}
    best_ti = max(float(row["target_improvement"]) for row in condition_rows)
    best_da = max(float(row["directional_accuracy"]) for row in condition_rows)
    ti_winners = {(row["model"], row["method"]) for row in condition_rows if float(row["target_improvement"]) == best_ti}
    da_winners = {(row["model"], row["method"]) for row in condition_rows if float(row["directional_accuracy"]) == best_da}
    shared = sorted(ti_winners & da_winners)
    result = {
        "status": "unique_shared_winner" if len(shared) == 1 else "no_unique_shared_winner",
        "highest_target_improvement": best_ti,
        "highest_directional_accuracy": best_da,
        "target_improvement_winners": [{"model": model, "method": method} for model, method in sorted(ti_winners)],
        "directional_accuracy_winners": [{"model": model, "method": method} for model, method in sorted(da_winners)],
    }
    if len(shared) == 1:
        model, method = shared[0]
        result["selected"] = {"model": model, "method": method}
    return result


def _paper_scope_pure(output: Path) -> bool:
    allowed_top_files = {"README.md", "PAPER_RESULTS_SUMMARY.json", "VALIDATION_REPORT.json", "MANIFEST.json"}
    for child in output.iterdir():
        if child.is_file() and child.name not in allowed_top_files:
            return False
        if child.is_dir() and child.name not in {"tables", "provenance"}:
            return False
    tables = output / "tables"
    if tables.exists() and {path.name for path in tables.iterdir() if path.is_file()} != EXPECTED_TABLE_FILES:
        return False
    provenance = output / "provenance"
    if provenance.exists() and {path.name for path in provenance.iterdir() if path.is_file()} != EXPECTED_PROVENANCE_FILES:
        return False
    return True


def build_paper_ready(project_root: Path, plan_path: Path, output: Path, overwrite: bool = False) -> dict[str, Any]:
    project_root = project_root.resolve()
    plan_path = _resolve(project_root, plan_path)
    plan = yaml.safe_load(plan_path.read_text(encoding="utf-8")) or {}
    paper_id = str(plan.get("paper_analysis_id") or "").strip()
    if not paper_id:
        raise RuntimeError("paper_analysis_id is required")
    if "evv2_4" not in output.name:
        raise RuntimeError("Paper-ready output artifact name must contain evv2_4")
    if output.exists():
        if not overwrite:
            raise FileExistsError(output)
        shutil.rmtree(output)
    output.mkdir(parents=True)

    model_entries = plan.get("models") or []
    primary_model = str(plan.get("primary_model") or "").strip()
    if len(model_entries) < 2:
        raise RuntimeError("Paper-ready plan requires at least two model entries")
    if not primary_model:
        raise RuntimeError("primary_model is required")

    checks: list[dict] = []
    warnings: list[dict] = []
    taskset_shas: set[str] = set()
    measurement_identities: list[dict] = []
    selected_eval_hashes: set[str] = set()
    source_refs: list[dict] = []
    pair_rows: list[dict] = []
    primary_feature_rows: list[dict] | None = None
    primary_interval_rows: list[dict] | None = None
    display_by_model: dict[str, str] = {}

    for entry in model_entries:
        model = str(entry["model"])
        display = str(entry.get("display_name") or model)
        display_by_model[model] = display
        pair_path = _resolve(project_root, entry["paired_summary"])
        manifest = read_json(pair_path / "paired_summary_manifest.json")
        summary = read_json(pair_path / "paired_summary.json")
        _check(checks, f"{model}:paired_contract", manifest.get("contract_id") == "storygen.paired-summary" and str(manifest.get("contract_version")) == "2.4")
        _check(checks, f"{model}:model_identity", manifest.get("rewrite_model") == model and summary.get("rewrite_model") == model)
        taskset_shas.add(str(manifest.get("taskset", {}).get("sha256")))
        identity = manifest.get("measurement_identity") or {}
        measurement_identities.append(identity)
        selected_eval_hashes.update({
            str(manifest.get("dp_evaluation", {}).get("manifest_sha256")),
            str(manifest.get("cg_evaluation", {}).get("manifest_sha256")),
        })
        source_refs.append({"role": "paired_summary", "model": model, "path": str(pair_path), "manifest_sha256": sha256_file(pair_path / "paired_summary_manifest.json")})
        pair_rows.append({
            "model_id": model,
            "model": display,
            "dp_valid": summary.get("dp_valid_n"),
            "cg_valid": summary.get("cg_valid_n"),
            "pair_n": summary.get("pair_n"),
            "dp_ti": summary.get("dp_target_improvement"),
            "cg_ti": summary.get("cg_target_improvement"),
            "dp_da": summary.get("dp_directional_accuracy"),
            "cg_da": summary.get("cg_directional_accuracy"),
        })
        if model == primary_model:
            primary_feature_rows = _typed_csv(pair_path / "paired_feature_summary.csv")
            primary_interval_rows = _typed_csv(pair_path / "paired_interval_summary.csv")

    _check(checks, "primary_model_present", primary_model in display_by_model)
    taskset_shas.discard("None")
    _check(checks, "all_paired_same_taskset", len(taskset_shas) == 1, detail=str(sorted(taskset_shas)))
    identity_texts = {json.dumps(identity, sort_keys=True) for identity in measurement_identities}
    _check(checks, "all_paired_same_measurement_identity", len(identity_texts) == 1)
    if primary_feature_rows is None or primary_interval_rows is None:
        raise RuntimeError("Primary model paired summary was not found")

    cross_cfg = plan.get("cross_model") or {}
    cross_path = _resolve(project_root, cross_cfg["analysis"])
    cross_manifest = read_json(cross_path / "cross_model_summary_manifest.json")
    cross_summary = read_json(cross_path / "cross_model_summary.json")
    _check(checks, "cross_contract_v2_4", cross_manifest.get("contract_id") == "storygen.cross-model-summary" and str(cross_manifest.get("contract_version")) == "2.4")
    _check(checks, "cross_analysis_set", cross_manifest.get("analysis_set_id") == cross_cfg.get("analysis_set_id"))
    _check(checks, "cross_taskset_matches", len(taskset_shas) == 1 and str(cross_manifest.get("taskset", {}).get("sha256")) in taskset_shas)
    cross_eval_hashes = {str(item.get("manifest_sha256")) for item in cross_manifest.get("evaluation_artifacts", [])}
    _check(checks, "cross_uses_exact_planned_evaluations", cross_eval_hashes == selected_eval_hashes, detail=f"cross={len(cross_eval_hashes)}, planned={len(selected_eval_hashes)}")
    _check(checks, "cross_model_count_matches_plan", int(cross_summary.get("model_count", -1)) == len(model_entries))
    source_refs.append({"role": "cross_model", "path": str(cross_path), "manifest_sha256": sha256_file(cross_path / "cross_model_summary_manifest.json")})

    repeat_cfg = plan.get("extractor_repeatability") or {}
    repeat_path = _resolve(project_root, repeat_cfg["summary"])
    repeat = read_json(repeat_path)
    expected_identity = measurement_identities[0] if measurement_identities else {}
    _check(checks, "repeatability_scene_count_100", int(repeat.get("scene_count", -1)) == 100)
    _check(checks, "repeatability_repeats_5", int(repeat.get("repeats", -1)) == 5)
    _check(checks, "repeatability_request_count_500", int(repeat.get("request_count", -1)) == 500)
    _check(checks, "repeatability_valid_count_500", int(repeat.get("valid_count", -1)) == 500)
    _check(checks, "repeatability_schema_failure_zero", float(repeat.get("schema_failure_rate", -1)) == 0.0)
    _check(checks, "repeatability_measurement_matches_benchmark", _identity_matches(expected_identity, repeat.get("measurement") or {}))
    per_feature = repeat.get("per_feature") or {}
    required_features = {"pacing", "dialogue_density", "action_density", "character_interaction", "emotion_intensity"}
    _check(checks, "repeatability_has_five_paper_features", required_features.issubset(set(per_feature)))
    source_refs.append({"role": "extractor_repeatability", "path": str(repeat_path), "sha256": sha256_file(repeat_path)})

    critical_failures = [check for check in checks if check["critical"] and check["status"] == "FAIL"]
    if critical_failures:
        validation = {
            "contract_id": "storygen.paper-ready-validation",
            "contract_version": "2.4",
            "paper_analysis_id": paper_id,
            "paper_ready": False,
            "checks": checks,
            "warnings": warnings,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        write_json(output / "VALIDATION_REPORT.json", validation)
        raise RuntimeError("Paper-ready validation failed: " + "; ".join(check["check"] for check in critical_failures))

    condition_rows = cross_summary.get("condition_summary") or []
    table6_rows = []
    for row in condition_rows:
        model_id = str(row.get("model"))
        table6_rows.append({
            "model": display_by_model.get(model_id, model_id),
            "condition": row.get("method"),
            "target_improvement": _fmt_percent(row.get("target_improvement")),
            "directional_accuracy": _fmt_percent(row.get("directional_accuracy")),
        })
    _write_table_pair(output, "table6_global_common", table6_rows,
                      [("model", "Model"), ("condition", "Condition"), ("target_improvement", "Target Improvement"), ("directional_accuracy", "Directional Accuracy")],
                      f"Main Benchmark Results on the Global Common Subset (N = {cross_summary.get('global_common_task_n')} identical tasks per row).")

    table7_rows = [{
        "model": row["model"],
        "dp_valid": row["dp_valid"],
        "cg_valid": row["cg_valid"],
        "pair_n": row["pair_n"],
        "dp_ti": _fmt_percent(row["dp_ti"]),
        "cg_ti": _fmt_percent(row["cg_ti"]),
        "dp_da": _fmt_percent(row["dp_da"]),
        "cg_da": _fmt_percent(row["cg_da"]),
    } for row in pair_rows]
    _write_table_pair(output, "table7_within_model_paired", table7_rows,
                      [("model", "Model"), ("dp_valid", "DP valid"), ("cg_valid", "CG valid"), ("pair_n", "Pair N"), ("dp_ti", "DP TI"), ("cg_ti", "CG TI"), ("dp_da", "DP DA"), ("cg_da", "CG DA")],
                      "Within-Model Paired Benchmark Results and Coverage.")

    feature_by_key = {_canonical_feature(row.get("feature")): row for row in primary_feature_rows}
    table8_rows = []
    for feature in TABLE8_FEATURE_ORDER:
        row = feature_by_key.get(feature)
        if not row:
            continue
        table8_rows.append({
            "feature": FEATURE_DISPLAY[feature],
            "pair_n": row.get("pair_n"),
            "dp_ti": _fmt_percent(row.get("dp_target_improvement")),
            "cg_ti": _fmt_percent(row.get("cg_target_improvement")),
            "dp_da": _fmt_percent(row.get("dp_directional_accuracy")),
            "cg_da": _fmt_percent(row.get("cg_directional_accuracy")),
        })
    _check(checks, "table8_has_five_features", len(table8_rows) == 5)
    _write_table_pair(output, "table8_primary_by_feature", table8_rows,
                      [("feature", "Feature"), ("pair_n", "Pair N"), ("dp_ti", "DP TI"), ("cg_ti", "CG TI"), ("dp_da", "DP DA"), ("cg_da", "CG DA")],
                      f"{display_by_model[primary_model]} Benchmark Results by Feature.")

    interval_by_key = {str(row.get("interval_type")): row for row in primary_interval_rows}
    table9_rows = []
    for interval in INTERVAL_ORDER:
        row = interval_by_key.get(interval)
        if not row:
            continue
        table9_rows.append({
            "interval": INTERVAL_DISPLAY[interval],
            "pair_n": row.get("pair_n"),
            "dp_ti": _fmt_percent(row.get("dp_target_improvement")),
            "cg_ti": _fmt_percent(row.get("cg_target_improvement")),
            "dp_da": _fmt_percent(row.get("dp_directional_accuracy")),
            "cg_da": _fmt_percent(row.get("cg_directional_accuracy")),
        })
    _check(checks, "table9_has_three_intervals", len(table9_rows) == 3)
    _write_table_pair(output, "table9_primary_by_length", table9_rows,
                      [("interval", "Interval"), ("pair_n", "Pair N"), ("dp_ti", "DP TI"), ("cg_ti", "CG TI"), ("dp_da", "DP DA"), ("cg_da", "CG DA")],
                      f"{display_by_model[primary_model]} Benchmark Results by Rewrite Length.")

    table10_rows = []
    for feature in TABLE10_FEATURE_ORDER:
        metrics = per_feature.get(feature) or {}
        table10_rows.append({
            "feature": FEATURE_DISPLAY[feature],
            "exact_5_repeat_agreement": _fmt_percent(metrics.get("exact_scene_agreement_rate"), 0),
            "mean_abs_deviation": _fmt_float(metrics.get("mean_absolute_repeated_score_deviation"), 5),
            "max_deviation": _fmt_float(metrics.get("maximum_observed_deviation"), 2),
            "spearman_rho": _fmt_float(metrics.get("repeat1_repeat2_spearman"), 4),
            "icc_3_1": _fmt_float(metrics.get("icc_3_1_consistency_single"), 4),
        })
    _write_table_pair(output, "table10_extractor_repeatability", table10_rows,
                      [("feature", "Feature"), ("exact_5_repeat_agreement", "Exact 5-repeat agreement"), ("mean_abs_deviation", "Mean abs. deviation"), ("max_deviation", "Max deviation"), ("spearman_rho", "Spearman rho"), ("icc_3_1", "ICC(3,1)")],
                      "Five-Repeat Computational Repeatability of the Fixed Feature Extractor (100 scenes, 500 total requests; 500/500 valid).")

    reference_baseline = _reference_baseline(condition_rows)
    compact_repeatability = {
        "source_sha256": sha256_file(repeat_path),
        "measurement_identity": expected_identity,
        "scene_count": repeat.get("scene_count"),
        "repeats": repeat.get("repeats"),
        "request_count": repeat.get("request_count"),
        "valid_count": repeat.get("valid_count"),
        "schema_failure_rate": repeat.get("schema_failure_rate"),
        "per_feature": per_feature,
    }

    (output / "provenance").mkdir(exist_ok=True)
    write_json(output / "provenance" / "SOURCE_ARTIFACTS.json", {"sources": source_refs})
    write_json(output / "provenance" / "GLOBAL_COMMON_TASK_IDS.json", {"analysis_set_id": cross_summary.get("analysis_set_id"), "task_ids": cross_summary.get("global_common_task_ids")})
    write_json(output / "provenance" / "REFERENCE_BASELINE.json", reference_baseline)
    write_json(output / "provenance" / "EXTRACTOR_REPEATABILITY_SUMMARY.json", compact_repeatability)

    results_summary = {
        "contract_id": "storygen.paper-results-summary",
        "contract_version": "2.4",
        "paper_analysis_id": paper_id,
        "evaluation_block_version": BLOCK_VERSION,
        "paper_ready": True,
        "primary_model": {"model": primary_model, "display_name": display_by_model[primary_model]},
        "benchmark_metrics": ["Target Improvement", "Directional Accuracy"],
        "global_common": {
            "analysis_set_id": cross_summary.get("analysis_set_id"),
            "n": cross_summary.get("global_common_task_n"),
            "condition_summary": condition_rows,
        },
        "within_model_paired": [{key: value for key, value in row.items() if key != "model_id"} for row in pair_rows],
        "reference_baseline": reference_baseline,
        "extractor_repeatability": compact_repeatability,
        "scope": {
            "distance_role": "Mean absolute distance is internal to Target Improvement and is not an independent benchmark outcome.",
            "coverage_role": "Valid/measurable task counts are reported separately and are not a benchmark score.",
            "extractor_repeatability_role": "Validated and packaged from Feature Extraction V1.4; not computed by Evaluation V2.4 and not a rewrite-performance metric.",
        },
    }
    write_json(output / "PAPER_RESULTS_SUMMARY.json", results_summary)

    bundle_readme = f"""# Paper-ready Evaluation V2.4 bundle

Paper analysis ID: `{paper_id}`

This bundle is intentionally restricted to the metrics and tables used by the Paper-22 benchmark.

Canonical contents:

1. `VALIDATION_REPORT.json` — provenance/readiness checks.
2. `PAPER_RESULTS_SUMMARY.json` — machine-readable paper-facing results.
3. `tables/table6_global_common.*` — global-common cross-model TI/DA.
4. `tables/table7_within_model_paired.*` — paired coverage, TI and DA.
5. `tables/table8_primary_by_feature.*` — primary-model feature stratification.
6. `tables/table9_primary_by_length.*` — primary-model rewrite-length stratification.
7. `tables/table10_extractor_repeatability.*` — validated Feature Extraction V1.4 repeatability handoff.
8. `provenance/` — source artifacts, global-common IDs, reference-baseline selection and compact repeatability provenance.

Evaluation V2.4 computes only Target Improvement and threshold-free Directional Accuracy for rewrite performance. Mean absolute distance is retained internally only to decide Target Improvement. Coverage is reported separately. The feature-extractor repeatability table is validated/packaged from the upstream Feature Extraction V1.4 reliability artifact; it is not recomputed here.

"""
    (output / "README.md").write_text(bundle_readme, encoding="utf-8")

    purity_ok = _paper_scope_pure(output)
    _check(checks, "paper_scope_purity", purity_ok, detail="Paper-ready bundle contains only the canonical Tables 6-10 and provenance layout.")
    critical_failures = [check for check in checks if check["critical"] and check["status"] == "FAIL"]
    validation = {
        "contract_id": "storygen.paper-ready-validation",
        "contract_version": "2.4",
        "paper_analysis_id": paper_id,
        "paper_ready": not critical_failures,
        "checks": checks,
        "warnings": warnings,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json(output / "VALIDATION_REPORT.json", validation)
    if critical_failures:
        raise RuntimeError("Paper-ready validation failed after table generation: " + "; ".join(check["check"] for check in critical_failures))

    manifest_files = []
    for path in sorted(file for file in output.rglob("*") if file.is_file() and file.name != "MANIFEST.json"):
        manifest_files.append({"path": str(path.relative_to(output)), "sha256": sha256_file(path)})
    manifest = {
        "contract_id": BUNDLE_CONTRACT_ID,
        "contract_version": BUNDLE_CONTRACT_VERSION,
        "evaluation_block_version": BLOCK_VERSION,
        "paper_analysis_id": paper_id,
        "paper_ready": True,
        "source_plan": {"path": str(plan_path), "sha256": sha256_file(plan_path)},
        "taskset_sha256": next(iter(taskset_shas)),
        "files": manifest_files,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json(output / "MANIFEST.json", manifest)

    zip_path = output.with_suffix(".zip")
    if zip_path.exists():
        if overwrite:
            zip_path.unlink()
        else:
            raise FileExistsError(zip_path)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(file for file in output.rglob("*") if file.is_file()):
            archive.write(path, arcname=str(Path(output.name) / path.relative_to(output)))

    return {"paper_ready": True, "output": str(output), "zip": str(zip_path), "manifest": manifest}


def validate_bundle(bundle: Path) -> dict[str, Any]:
    bundle = bundle.resolve()
    validation = read_json(bundle / "VALIDATION_REPORT.json")
    manifest = read_json(bundle / "MANIFEST.json")
    checks: list[dict] = []
    _check(checks, "paper_ready_validation", validation.get("paper_ready") is True)
    _check(checks, "manifest_contract", manifest.get("contract_id") == BUNDLE_CONTRACT_ID and str(manifest.get("contract_version")) == BUNDLE_CONTRACT_VERSION)
    for entry in manifest.get("files", []):
        path = bundle / entry["path"]
        _check(checks, f"hash:{entry['path']}", path.is_file() and sha256_file(path) == entry["sha256"])
    _check(checks, "paper_scope_purity", _paper_scope_pure(bundle))
    valid = all(check["status"] == "PASS" for check in checks)
    return {"valid": valid, "bundle": str(bundle), "checks": checks}
