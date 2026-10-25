"""All domain fixtures are synthetic numbers, never historical measurements."""

from pathlib import Path
import copy
import importlib.util
import sys
import pytest

# Isolated subprocesses use the same ordinary PYTHONPATH import root as local engines.
# Tests register explicit module specs without changing sys.path or another experiment.
HOME = Path(__file__).resolve().parents[1]
for name in (
    "common",
    "validate",
    "bindings",
    "analyze",
    "aggregate",
    "report",
    "engine",
):
    spec = importlib.util.spec_from_file_location(name, HOME / "src" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)

FEATURES = sys.modules["common"].FEATURES
rewrite_identity = sys.modules["common"].rewrite_identity


@pytest.fixture
def canonical():
    return dict(
        measurement_protocol_id="synthetic-protocol",
        protocol_hash="synthetic-hash",
        prompt_hash="prompt",
        schema_hash="schema",
        system_instruction_hash="system",
        request_contract_hash="request",
        decoding_hash="decoding",
    )


@pytest.fixture
def record_factory(canonical):
    def make(
        n=2,
        task_id="t1",
        base="b1",
        model="qwen25_7b",
        condition="DP-v1",
        target=0,
        after=0.7,
    ):
        ids = [f"s{i}" for i in range(n)]
        task = dict(
            task_id=task_id,
            base_interval_id=base,
            source_film_id="film",
            reference_film_id="reference",
            source_scene_ids=ids,
            reference_scene_ids=[f"r{i}" for i in range(n)],
            selected_features=[FEATURES[target]],
            source_scene_count=n,
        )

        def row(scene_id, value):
            return dict(
                film_id="film",
                scene_id=scene_id,
                measurement_protocol_id=canonical["measurement_protocol_id"],
                measurement_protocol_hash=canonical["protocol_hash"],
                **{
                    k: canonical[k]
                    for k in (
                        "prompt_hash",
                        "schema_hash",
                        "system_instruction_hash",
                        "request_contract_hash",
                        "decoding_hash",
                    )
                },
                **{f: value for f in FEATURES},
            )

        before = [row(i, 0.5) for i in ids]
        refs = dict(
            rewrite=dict(sha256="sha256:rewrite"), plan=dict(sha256="sha256:plan")
        )
        artifacts = dict(
            task=copy.deepcopy(task),
            plan=dict(
                run_id=task_id,
                source_scene_ids=ids,
                reference_scene_ids=task["reference_scene_ids"],
                selected_features=task["selected_features"],
                per_scene_target_values=[
                    dict(
                        scene_id=i,
                        deltas={FEATURES[target]: 0.1 if index % 2 else -0.1},
                    )
                    for index, i in enumerate(ids)
                ],
            ),
            phase=dict(
                task_id=task_id,
                source_scene_ids=ids,
                prompt_contract_id=condition,
                rewrite_completed=True,
            ),
            rewrite=dict(scene_ids=ids),
            after=[row(i, after) for i in ids],
            measurement_status=dict(
                status="measured",
                measurement=canonical,
                source_feature_measurement=canonical,
                contract_equality_verified=True,
                source_rewrite_artifact_sha256=rewrite_identity(refs),
                scene_ids=ids,
            ),
        )
        return dict(
            model=model,
            condition=condition,
            task=task,
            artifacts=artifacts,
            artifact_refs=refs,
        ), before

    return make


@pytest.fixture
def prepared(record_factory, canonical):
    record, before = record_factory()
    return dict(
        binding={"measurement": canonical}, originals={"film": before}, records=[record]
    )
