import copy
import json
from pathlib import Path
import subprocess
import sys
import pytest
from common import (
    FEATURES,
    SHORT,
    MODELS,
    CONDITIONS,
    EPSILON,
    direction,
    numeric,
    read,
    sha,
    write,
    BindingError,
)
from bindings import population, load_ref
from validate import validate
from analyze import calculate
from aggregate import matrices, common_ids, paired, coverage, describe, aggregate
from report import csv_table


def synthetic_population():
    tasks = []
    for base in range(48):
        n = (5, 8, 12)[base % 3]
        for i, f in enumerate(FEATURES):
            tasks.append(
                dict(
                    task_id=f"t{base * 5 + i:03d}",
                    base_interval_id=f"b{base:02d}",
                    source_film_id=f"film{base % 10}",
                    source_scene_ids=[f"s{j}" for j in range(n)],
                    source_scene_count=n,
                    selected_features=[f],
                )
            )
    return {"tasks": tasks}


def task_rows(prepared):
    v = validate(prepared)
    return calculate(v)[1]


def test_five_features_and_one_target():
    assert len(FEATURES) == len(set(FEATURES)) == 5
    assert len(SHORT) == 5
    assert FEATURES[1] == "llm_dialogue_density_score"


def test_population_all_definitions_and_enumeration():
    tasks = population(synthetic_population())
    assert len(tasks) == 240 and len({t["base_interval_id"] for t in tasks}) == 48
    assert len(MODELS) * len(CONDITIONS) * len(tasks) == 1920
    assert sum(len(t["source_scene_ids"]) for t in tasks) * 8 == 16000


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate_task",
        "missing_task",
        "wrong_feature",
        "wrong_base",
        "scene_duplicate",
        "scene_count",
        "wrong_film_count",
    ],
)
def test_population_rejects_corrupt(mutation):
    v = synthetic_population()
    if mutation == "duplicate_task":
        v["tasks"][1]["task_id"] = v["tasks"][0]["task_id"]
    if mutation == "missing_task":
        v["tasks"].pop()
    if mutation == "wrong_feature":
        v["tasks"][0]["selected_features"] = ["unknown"]
    if mutation == "wrong_base":
        v["tasks"][0]["base_interval_id"] = "another"
    if mutation == "scene_duplicate":
        v["tasks"][0]["source_scene_ids"][1] = "s0"
    if mutation == "scene_count":
        v["tasks"][0]["source_scene_count"] = 1
    if mutation == "wrong_film_count":
        for t in v["tasks"]:
            t["source_film_id"] = "one"
    with pytest.raises(BindingError):
        population(v)


def test_alignment_signed_absolute_target_and_nontarget(prepared):
    validated = validate(prepared)
    scenes, tasks = calculate(validated)
    assert tasks[0]["status"] == "COMPLETE"
    assert scenes[0]["delta_pacing"] == pytest.approx(0.2)
    assert scenes[0]["abs_delta_pacing"] == pytest.approx(0.2)
    assert scenes[0]["before_pacing"] == 0.5 and scenes[0]["after_pacing"] == 0.7
    assert tasks[0]["target_feature"] == FEATURES[0]
    assert scenes[0]["non_target_features"] == list(FEATURES[1:])
    assert tasks[0]["mean_signed_target_change"] == pytest.approx(0.2)
    assert tasks[0]["mean_absolute_non_target_drift"] == pytest.approx(0.2)
    assert scenes[0]["scene_order"] == 1 and scenes[0]["scene_id"] == "s0"
    assert tasks[0]["target_direction"] == "MIXED"


def test_cancellation_and_direction_strata(prepared):
    for f in FEATURES:
        prepared["records"][0]["artifacts"]["after"][0][f] = 0.8
        prepared["records"][0]["artifacts"]["after"][1][f] = 0.2
    rows = task_rows(prepared)
    row = rows[0]
    assert row["mean_signed_pacing"] == pytest.approx(0)
    assert row["mean_absolute_pacing"] == pytest.approx(0.3)
    assert row["median_absolute_pacing"] == pytest.approx(0.3)
    assert row["pacing_increase_count"] == row["pacing_decrease_count"] == 1
    assert row["pacing_increase_rate"] == 0.5
    matrix = matrices(rows)
    cells = [
        r
        for r in matrix
        if r["model"] == "qwen25_7b"
        and r["condition"] == "DP-v1"
        and r["target_feature"] == FEATURES[0]
        and r["measured_feature"] == FEATURES[0]
        and r["statistic"] == "mean_signed_change"
    ]
    by_dir = {r["target_direction"]: r["mean"] for r in cells}
    assert by_dir["INCREASE"] == pytest.approx(-0.3)
    assert by_dir["DECREASE"] == pytest.approx(0.3)
    assert by_dir["MAINTAIN"] is None


@pytest.mark.parametrize(
    "delta,expected",
    [
        (2.8e-17, "UNCHANGED"),
        (EPSILON, "UNCHANGED"),
        (-EPSILON, "UNCHANGED"),
        (2 * EPSILON, "INCREASE"),
        (-2 * EPSILON, "DECREASE"),
    ],
)
def test_epsilon(delta, expected):
    assert direction(delta) == expected


def test_epsilon_does_not_zero_deltas(prepared):
    prepared["records"][0]["artifacts"]["after"][0][FEATURES[0]] = 0.5 + 5e-13
    scene = calculate(validate(prepared))[0][0]
    assert 0 < scene["delta_pacing"] < EPSILON


def test_equal_weight_matrix_different_lengths(record_factory, canonical):
    a, before = record_factory(n=2, task_id="short", base="b1", after=0.6)
    b, before_long = record_factory(n=12, task_id="long", base="b2", after=0.9)
    # Source identities are shared consistently; two distinct outcomes remain tasks.
    p = dict(
        binding={"measurement": canonical},
        originals={"film": before_long},
        records=[a, b],
    )
    rows = task_rows(p)
    assert len(rows) == 2
    cell = next(
        r
        for r in matrices(rows)
        if r["model"] == "qwen25_7b"
        and r["condition"] == "DP-v1"
        and r["target_feature"] == r["measured_feature"] == FEATURES[0]
        and r["statistic"] == "mean_absolute_change"
        and r["target_direction"] == "ALL"
    )
    assert cell["mean"] == pytest.approx(0.25)
    assert cell["mean"] != pytest.approx((0.1 * 2 + 0.4 * 12) / 14)
    assert cell["n_tasks"] == 2 and cell["eligible_scene_pairs"] == 14


@pytest.mark.parametrize(
    "kind,expected", [("rewrite", "MISSING_REWRITE"), ("after", "MISSING_REANALYSIS")]
)
def test_missing_historical_outputs(prepared, kind, expected):
    prepared["records"][0]["artifacts"][kind] = None
    v = validate(prepared)
    task = calculate(v)[1][0]
    assert task["status"] == expected
    assert task["mean_absolute_non_target_drift"] is None
    assert len(v["exclusions"]) == 3
    cov = coverage([task])[0]
    assert cov["planned_tasks"] == cov["missing_tasks"] == 1
    assert cov["expected_scene_slots"] == cov["missing_scene_pairs"] == 2


def test_partial_denominator_and_null_task_metrics(prepared):
    prepared["records"][0]["artifacts"]["after"].pop()
    v = validate(prepared)
    scenes, tasks = calculate(v)
    assert tasks[0]["status"] == "PARTIAL"
    assert (tasks[0]["valid_scenes"], tasks[0]["missing_scenes"]) == (1, 1)
    assert tasks[0]["mean_absolute_non_target_drift"] is None
    assert scenes[0]["delta_pacing"] is not None and scenes[1]["delta_pacing"] is None
    assert coverage(tasks)[0]["partial_measurement_tasks"] == 1


@pytest.mark.parametrize(
    "value", [None, True, "0.5", float("nan"), float("inf"), -0.1, 1.1]
)
def test_invalid_values(prepared, value):
    assert not numeric(value)
    prepared["records"][0]["artifacts"]["after"][0][FEATURES[2]] = value
    task = task_rows(prepared)[0]
    assert task["status"] == "PARTIAL" and task["invalid_scenes"] == 1
    assert task["mean_absolute_target_change"] is None


@pytest.mark.parametrize(
    "mutation",
    [
        "protocol",
        "wrong_scene",
        "wrong_film",
        "wrong_order",
        "duplicate_scene",
        "wrong_task",
        "wrong_plan",
        "wrong_phase",
        "input_hash",
        "instrument",
    ],
)
def test_incompatible_or_misaligned(prepared, mutation):
    r = prepared["records"][0]
    a = r["artifacts"]
    if mutation == "protocol":
        for row in a["after"]:
            row["measurement_protocol_hash"] = "mistral"
    if mutation == "wrong_scene":
        a["after"][0]["scene_id"] = "wrong"
    if mutation == "wrong_film":
        a["after"][0]["film_id"] = "other"
    if mutation == "wrong_order":
        a["after"].reverse()
    if mutation == "duplicate_scene":
        a["after"][1] = copy.deepcopy(a["after"][0])
    if mutation == "wrong_task":
        a["task"]["task_id"] = "another"
    if mutation == "wrong_plan":
        a["plan"]["source_scene_ids"] = list(reversed(a["plan"]["source_scene_ids"]))
    if mutation == "wrong_phase":
        a["phase"]["prompt_contract_id"] = "wrong"
    if mutation == "input_hash":
        a["measurement_status"]["source_rewrite_artifact_sha256"] = "other"
    if mutation == "instrument":
        a["measurement_status"]["measurement"] = {}
    task = task_rows(prepared)[0]
    assert task["status"] in ("MEASUREMENT_MISMATCH", "IDENTITY_MISMATCH")
    assert task["invalid_scenes"] == 2 and task["valid_scenes"] == 0


def test_duplicate_task_records_rejected(prepared):
    prepared["records"].append(copy.deepcopy(prepared["records"][0]))
    with pytest.raises(BindingError, match="Duplicate"):
        validate(prepared)


def test_exact_population_coverage(prepared):
    task = task_rows(prepared)[0]
    rows = [
        dict(task, model=m, condition=c, task_id=f"t{i}")
        for m in MODELS
        for c in CONDITIONS
        for i in range(240)
    ]
    cov = coverage(rows)
    assert len(cov) == 8 and sum(c["planned_tasks"] for c in cov) == 1920
    for c in cov:
        assert c["planned_tasks"] == sum(
            c[k]
            for k in (
                "complete_measurement_tasks",
                "partial_measurement_tasks",
                "missing_tasks",
                "invalid_tasks",
            )
        )
        assert c["expected_scene_slots"] == sum(
            c[k]
            for k in ("valid_scene_pairs", "missing_scene_pairs", "invalid_scene_pairs")
        )


def test_dp_cg_intersection_and_controlled_row(prepared):
    task = task_rows(prepared)[0]
    dp = [dict(task, task_id=t) for t in ("a", "b")]
    cg = [
        dict(task, task_id=t, condition="CG-v1", mean_absolute_non_target_drift=0.4)
        for t in ("b", "c")
    ]
    rows = paired(dp + cg)
    summary = next(
        r
        for r in rows
        if r["model"] == "qwen25_7b"
        and r["record_type"] == "SUMMARY"
        and r["metric"] == "mean_absolute_non_target_drift"
    )
    assert summary["n_tasks"] == 1 and summary["mean"] == pytest.approx(0.2)
    assert (
        summary["dp_total_measurable_tasks"]
        == summary["cg_total_measurable_tasks"]
        == 2
    )
    cells = [
        r
        for r in rows
        if r["record_type"] == "TASK_DIFFERENCE" and r["target_feature"] != "ALL"
    ]
    assert len(cells) == 10 and {r["target_feature"] for r in cells} == {FEATURES[0]}


def test_global_all_eight_complete_intersection(prepared):
    task = task_rows(prepared)[0]
    rows = [
        dict(task, model=m, condition=c, task_id=t)
        for m in MODELS
        for c in CONDITIONS
        for t in ("a", "b")
    ]
    assert common_ids(rows) == {"a", "b"}
    rows[-1]["status"] = "PARTIAL"
    assert common_ids(rows) == {"a"}
    assert common_ids(rows[:-2]) == set()


def test_cluster_bootstrap_repeated_base_dependence():
    rows = [
        dict(
            task_id=f"{b}_{i}",
            base_interval_id=str(b),
            source_film_id="film",
            metric=float(b),
        )
        for b in range(8)
        for i in range(5)
    ]
    result = describe(rows, "metric")
    assert result["n_tasks"] == 40 and result["eligible_clusters"] == 8
    assert result["bootstrap_replications"] == 2000
    assert result == describe(list(reversed(rows)), "metric")
    # Five identical task copies per cluster do not shrink the cluster CI.
    one = describe(rows[::5], "metric")
    assert (one["ci95_low"], one["ci95_high"]) == (
        result["ci95_low"],
        result["ci95_high"],
    )
    assert result["ci95_low"] < result["mean"] < result["ci95_high"]


def test_insufficient_clusters_and_empty_statistics():
    assert describe([], "value")["mean"] is None
    assert describe([], "value")["ci95_low"] is None
    assert describe([], "value")["eligible_clusters"] == 0
    one = describe(
        [dict(task_id="t", base_interval_id="b", source_film_id="f", value=0.2)],
        "value",
    )
    assert one["standard_deviation"] is None and one["bootstrap_replications"] == 0


def test_csv_nulls_precision_and_deterministic_columns(tmp_path):
    csv_table(tmp_path / "one.csv", [dict(z=None, task_id="a", value=0.25)])
    assert (
        tmp_path / "one.csv"
    ).read_text() == "task_id,value,z\na,0.25000000000000000,NA\n"
    with pytest.raises(FileExistsError):
        csv_table(tmp_path / "one.csv", [])


def test_immutable_hash_binding_changed_or_appeared(tmp_path):
    f = tmp_path / "fixture.json"
    missing = dict(path=str(f), sha256=None)
    assert load_ref(missing) is None
    write(f, {"x": 1})
    with pytest.raises(BindingError, match="appeared"):
        load_ref(missing)
    ref = dict(path=str(f), sha256=sha(f))
    assert load_ref(ref) == {"x": 1}
    f.write_text('{"x":2}')
    with pytest.raises(BindingError, match="changed"):
        load_ref(ref)
    with pytest.raises(FileExistsError):
        write(f, {})


def test_duplicate_json_keys_rejected(tmp_path):
    f = tmp_path / "bad.json"
    f.write_text('{"a":1,"a":2}')
    with pytest.raises(BindingError):
        read(f)


def test_deterministic_output_order_and_empty_groups(prepared):
    v = validate(prepared)
    scenes, tasks = calculate(v)
    first = aggregate(v, scenes, tasks)
    second = aggregate(v, scenes, tasks)
    assert first == second
    assert len(first["coverage"]) == 8
    assert len(first["global_common"]) == 8 * 13
    assert all(r["mean"] is None for r in first["global_common"])
    assert len(first["matrices"]) == 8 * 25 * 4 * 5 * 2


def test_no_inference_or_cross_experiment_execution_paths():
    root = Path(__file__).resolve().parents[1]
    for path in (root / "src").glob("*.py"):
        text = path.read_text()
        for forbidden in (
            "import requests",
            "import httpx",
            "import socket",
            "import urllib",
            "import subprocess",
            "import storygen_feature",
            "import storygen_measurement",
            "import storygen_evaluation",
            "from experiments",
            "import llama_cpp",
        ):
            assert forbidden not in text
    pipeline = json.loads((root / "pipeline.yaml").read_text())
    assert [s["stage_id"] for s in pipeline["stages"]] == [
        "prepare",
        "validate",
        "analyze",
        "report",
    ]
    assert all(s["adapter"]["kind"] == "local_engine" for s in pipeline["stages"])
    lock = json.loads((root / "dependencies.lock.yaml").read_text())
    assert lock["models"] == lock["backend_files"] == lock["providers"] == []


def test_local_cli_safe_help_and_ambiguous_selection():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [str(root / "e05-feature-diff"), "--help"], capture_output=True, text=True
    )
    assert result.returncode == 0 and result.stdout.startswith(
        "====================================================\n                 E05-4-FEATURE-DIFF"
    )
    result = subprocess.run(
        [str(root / "e05-feature-diff"), "status", "--run-id", "../escape"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2


def test_report_and_figures_from_synthetic_tables_only(tmp_path, prepared):
    from report import render
    from jsonschema import Draft202012Validator

    v = validate(prepared)
    scenes, tasks = calculate(v)
    data = aggregate(v, scenes, tasks)
    summary = render(tmp_path, data)
    assert summary["llm_inference"] is False
    assert summary["scientific_validity_verified"] is False
    assert summary["figures"]["status"] == "GENERATED"
    assert len(summary["figures"]["files"]) == 38
    assert len(list(tmp_path.glob("*.pdf"))) == 19
    assert len(list(tmp_path.glob("*.png"))) == 19
    assert all(
        (tmp_path / name).is_file()
        for name in (
            "01_COVERAGE.csv",
            "02_SCENE_FEATURE_DIFF.csv",
            "03_TASK_FEATURE_DIFF.csv",
            "04_FEATURE_INTERACTION_MATRIX.csv",
            "05_NON_TARGET_DRIFT.csv",
            "06_DP_CG_COMPARISON.csv",
            "07_MODEL_COMPARISON.csv",
            "08_EXCLUSIONS.csv",
            "09_DIRECTION_DISTRIBUTION.csv",
            "10_GLOBAL_COMMON_COMPARISON.csv",
            "E05_4_FEATURE_DIFF_REPORT.md",
            "E05_4_FEATURE_DIFF_TECHNICAL.md",
            "E05_4_FEATURE_DIFF_LIMITATIONS.md",
            "scientific_summary.json",
            "input_provenance.json",
            "artifact_manifest.json",
        )
    )
    manifest = json.loads((tmp_path / "artifact_manifest.json").read_text())
    for entry in manifest["artifacts"]:
        assert sha(tmp_path / entry["path"]) == entry["sha256"]
    assert len(manifest["artifacts"]) == 58
    report = (tmp_path / "E05_4_FEATURE_DIFF_REPORT.md").read_text()
    assert (
        "Largest observed task drift" in report
        and "Most frequent non-target decrease" in report
    )
    root = Path(__file__).resolve().parents[1]
    Draft202012Validator(
        json.loads((root / "src/assets/schemas/report.schema.json").read_text())
    ).validate(dict(summary, population_tasks=1920))
    with pytest.raises(FileExistsError):
        render(tmp_path, data)


def test_optional_plot_dependency_unavailable(tmp_path, monkeypatch):
    from report import plots

    monkeypatch.setitem(sys.modules, "matplotlib", None)
    result = plots(tmp_path, {})
    assert result["status"] == "OPTIONAL_DEPENDENCY_UNAVAILABLE"
    assert result["files"] == [] and list(tmp_path.iterdir()) == []


def test_central_create_only_store_and_interrupted_sealing(tmp_path):
    from storygen_experiment.artifact_store import Store
    from storygen_experiment import runtime

    # Minimal synthetic central fixture tests ownership and interruption without
    # running the real experiment's prepare/analyze/report pipeline.
    depot = tmp_path / "depot"
    depot.mkdir()
    (depot / "DEPOT_MANIFEST.json").write_text(
        json.dumps(
            {"depot_id": "storygen-experiment-depot", "owner": "storygen-experiment"}
        )
    )
    home = Path(__file__).resolve().parents[1]
    manifest = json.loads((home / "experiment.yaml").read_text())
    lock = dict(
        experiment=manifest,
        run_id="synthetic_immutable",
        pipeline={"stages": []},
        configuration={"purpose": "SYNTHETIC_TEST"},
        runner={},
        resolved_providers=[],
        resolved_inputs=[],
    )
    store = Store(depot, lock).create()
    with pytest.raises(FileExistsError):
        Store(depot, lock).create()
    result = store.seal("INTERRUPTED", [], [])
    assert result["execution_status"] == "INTERRUPTED"
    assert (store.root / "integrity/SEALED.json").is_file()
    with pytest.raises(FileExistsError):
        store.seal("COMPLETE", [], [])
    assert (
        runtime.sha(store.root / "run_manifest.json")
        == json.loads((store.root / "integrity/SEALED.json").read_text())[
            "manifest_sha256"
        ]
    )


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_invalid_json_numeric_tokens_can_be_classified(tmp_path, prepared, token):
    f = tmp_path / "invalid.json"
    f.write_text('{"value":' + token + "}")
    value = read(f)["value"]
    assert not numeric(value)
    prepared["records"][0]["artifacts"]["after"][0][FEATURES[0]] = value
    write(tmp_path / "prepared.json", prepared)
    assert task_rows(prepared)[0]["invalid_scenes"] == 1


def test_source_order_validated_separately(prepared):
    prepared["originals"]["film"].reverse()
    assert task_rows(prepared)[0]["status"] == "IDENTITY_MISMATCH"


def test_invalid_status_and_row_shape(prepared):
    prepared["records"][0]["artifacts"]["measurement_status"]["status"] = "failed"
    assert task_rows(prepared)[0]["status"] == "INVALID_MEASUREMENT"
    prepared["records"][0]["artifacts"]["measurement_status"]["status"] = "measured"
    prepared["records"][0]["artifacts"]["after"] = ["bad-record"]
    assert task_rows(prepared)[0]["status"] == "INVALID_MEASUREMENT"
