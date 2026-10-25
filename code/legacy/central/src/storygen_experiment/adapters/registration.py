"""Generate a thin central description of an exact published M13 native protocol."""

from pathlib import Path
import hashlib
import json
from storygen_experiment import ROOT, runtime, registry


def native_spec(
    workspace,
    owner,
    slug,
    commit,
    config,
    *,
    central_id=None,
    group=None,
    selected_stages=None,
    central_protocol=None,
):
    workspace = Path(workspace)
    source = workspace / owner
    if (
        runtime.git(source, "rev-parse", "experiment-architecture-v1.0.0^{commit}")
        != commit
    ):
        raise ValueError("M13 release anchor mismatch")
    names = runtime.git(source, "ls-tree", "-r", "--name-only", commit).splitlines()
    manifest_path = next(
        p for p in names if p.endswith("/" + slug + "/experiment.yaml")
    )
    native = json.loads(
        __import__("subprocess").check_output(
            ["git", "-C", str(source), "show", commit + ":" + manifest_path]
        )
    )
    lock_path = str(Path(manifest_path).parent / "dependencies.lock.yaml")
    lock_bytes = __import__("subprocess").check_output(
        ["git", "-C", str(source), "show", commit + ":" + lock_path]
    )
    native_lock = json.loads(lock_bytes)
    key = central_id or slug
    group = group or native["group_id"]
    home = ROOT / "experiments" / group / key
    cfg_payload = (json.dumps(config, indent=2) + "\n").encode()
    inputs = [
        dict(
            name="native_configuration",
            contract="storygen.m13.configuration/" + native["protocol_id"],
            schema={
                "type": "object",
                "required": ["purpose", "inputs"],
                "properties": {
                    "purpose": {"enum": ["MIGRATION_VERIFICATION", "RESEARCH"]},
                    "inputs": {"type": "object"},
                },
            },
        )
    ]
    originals = [
        s
        for s in native["stages"]
        if selected_stages is None or s["stage_id"] in selected_stages
    ]
    chosen = {s["stage_id"] for s in originals}
    stages = []
    for node in originals:
        stage = node["stage_id"]
        deps = [k for k in node["depends_on"] if k in chosen]
        bindings = [
            dict(
                name="native_configuration",
                contract=inputs[0]["contract"],
                binding=dict(input="native_configuration"),
            )
        ]
        bindings += [
            dict(
                name="prior_" + k,
                contract="storygen.m13.stage/" + native["protocol_id"] + "/" + k,
                binding=dict(stage=k, output="native_result"),
            )
            for k in deps
        ]
        stages.append(
            dict(
                stage_id=stage,
                provider=node["provider_repo"],
                depends_on=deps,
                inputs=bindings,
                outputs=[
                    dict(
                        role="native_result",
                        contract="storygen.m13.stage/"
                        + native["protocol_id"]
                        + "/"
                        + stage,
                        path="result.json",
                        schema={
                            "type": "object",
                            "required": [
                                "status",
                                "native_stage_id",
                                "native_protocol_id",
                                "outputs",
                                "scientific_validity",
                            ],
                            "properties": {
                                "status": {"const": "COMPLETE"},
                                "native_stage_id": {"const": stage},
                                "native_protocol_id": {"const": native["protocol_id"]},
                                "outputs": {"type": "array", "minItems": 1},
                                "scientific_validity": {"const": "UNVERIFIED"},
                            },
                        },
                    )
                ],
                adapter=dict(kind="m13_stage", delegate="native", native_stage=stage),
                parameters={},
                resources=dict(profile="native_" + stage, work_units=1),
            )
        )
    science = dict(
        question=native["scientific_question"],
        hypotheses=[native["hypothesis"]],
        independent_variables=native["independent_variables"],
        controls=native["control_components"],
        population=native["sample_population"],
        unit_of_analysis=native["unit_of_analysis"],
        metrics=["Definitions and estimators in the unchanged exact native protocol"],
        acceptance_criteria=[
            "Native scientific validators pass; inputs/outputs are traceable and immutable; technical execution is distinct from scientific validity"
        ],
        limitations=[
            *native["research_limitations"],
            "Central verification is engineering only; the native scientific protocol and historical results remain authoritative.",
        ],
        classification="verification_only"
        if selected_stages is not None
        else "research",
    )
    if selected_stages is not None:
        science.update(
            question="Does exact native "
            + slug
            + " preparation run safely under central output ownership?",
            population="Original locked preparation population; no inference stages executed",
            acceptance_criteria=[
                "Selected native preparation/strict preflight actions succeed; no inference; old depots unchanged"
            ],
        )
    experiment = dict(
        schema_version="storygen.central-experiment/1.0",
        experiment_id=key,
        group_id=group,
        protocol_id=central_protocol or native["protocol_id"],
        protocol_version="1.0.0",
        runner=key + ".py",
        pipeline="pipeline.yaml",
        science=science,
        component_reuse=[
            dict(
                component=value,
                rationale="Unaltered frozen reference dependency selected by the authoritative native protocol",
                altered=False,
            )
            for value in native["control_components"]
        ],
        historical_delegation=dict(
            owner_repo=owner,
            experiment_id=slug,
            protocol_id=native["protocol_id"],
            source_commit=commit,
            public_runner=native["public_runner"],
        ),
    )
    models = {}
    for role in [
        "profile",
        "server_manifest",
        "rewrite_server_manifest",
        "measurement_server_manifest",
    ]:
        if role not in config.get("inputs", {}):
            continue
        path = Path(config["inputs"][role]["path"])
        if not path.exists():
            continue
        profile = registry.read(path)
        model = profile.get("model", profile)
        checkpoint = model.get("checkpoint_path") or model.get("model_path")
        for value in native_lock["models"]:
            if (
                checkpoint
                and Path(value["path"]).resolve() == Path(checkpoint).resolve()
            ):
                models[value["path"]] = value
    return dict(
        experiment=experiment,
        pipeline=dict(
            schema_version="storygen.central-pipeline/1.0",
            experiment_id=key,
            inputs=inputs,
            stages=stages,
        ),
        dependencies=dict(
            providers=[
                dict(
                    repo_id=owner,
                    commit=commit,
                    tree_sha256=runtime.committed_tree(source, commit),
                    components=[],
                )
            ],
            delegates={
                "native": dict(
                    repo_id=owner,
                    commit=commit,
                    runner=native["public_runner"],
                    experiment_sha256="sha256:"
                    + hashlib.sha256(
                        __import__("subprocess").check_output(
                            [
                                "git",
                                "-C",
                                str(source),
                                "show",
                                commit + ":" + manifest_path,
                            ]
                        )
                    ).hexdigest(),
                    dependency_lock_sha256="sha256:"
                    + hashlib.sha256(lock_bytes).hexdigest(),
                )
            },
            models=list(models.values()),
            backend_files=native_lock["runtime_profile"].get("backend_files", []),
        ),
        scientific_assets={"native_configuration.json": config},
        run_configuration=dict(
            purpose=config["purpose"],
            inputs={
                "native_configuration": dict(
                    path=str(home / "src/assets/native_configuration.json"),
                    sha256="sha256:" + hashlib.sha256(cfg_payload).hexdigest(),
                )
            },
        ),
    )
