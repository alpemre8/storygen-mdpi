"""Stage-oriented foreground execution, stable-ID joins and same-run recovery."""

from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
import json
import uuid
import jsonschema
from . import dag, scientific
from .artifacts import RunStore
from .common import StoryGenError, contained, digest, file_sha, read, utc, write_json, identifier
from .runtime import TransportError, ServerManager, gpu_lease, verify_profile


class ScientificResponseError(StoryGenError):
    pass


def experiment(root, key, *, catalog="experiments"):
    if catalog not in {"experiments", "analyses"}:
        raise StoryGenError("Unknown scientific catalog")
    home = contained(Path(root) / catalog, identifier(key))
    if not (home / "experiment.yaml").is_file():
        raise StoryGenError(f"Unknown experiment: {key}")
    definition = scientific.validate_definition(read(home / "experiment.yaml"))
    if definition["experiment_id"] != key:
        raise StoryGenError("Experiment directory identity mismatch")
    return home, definition, read(home / "pipeline.yaml")


def population(root, home, depot, definition):
    ref = definition["population"]
    if ref.get("access") != "open":
        raise StoryGenError(
            "Sealed/unknown population access is blocked in DEV and SCIENTIFIC modes"
        )
    base = {"depot": depot, "experiment": home}.get(ref["root"])
    if base is None:
        raise StoryGenError("Unknown population storage root")
    path = contained(base, ref["path"])
    if not path.is_file():
        raise StoryGenError(f"Missing population file {path}")
    if file_sha(path) != ref["sha256"]:
        raise StoryGenError("Frozen task population hash mismatch")
    data = json.loads(path.read_text())
    tasks = data["tasks"] if isinstance(data, dict) else data
    if len(tasks) != ref["expected_tasks"]:
        raise StoryGenError("Task population denominator mismatch")
    ids = [identifier(t["task_id"]) for t in tasks]
    if len(set(ids)) != len(ids):
        raise StoryGenError("Duplicate stable task IDs")
    return sorted(tasks, key=lambda t: t["task_id"]), {
        "root": ref["root"],
        "path": ref["path"],
        "sha256": file_sha(path),
        "count": len(tasks),
    }


def preflight(
    root,
    depot,
    registry,
    key,
    profile,
    *,
    require_approval=True,
    verify_files=True,
    catalog="experiments",
    selected_stages=None,
    historical_sources=None,
):
    home, definition, pipeline = experiment(root, key, catalog=catalog)
    nodes = dag.plan(pipeline, registry)
    source_values = {}
    source_provenance = {}
    historical_sources = historical_sources or {}
    if selected_stages:
        if len(set(selected_stages)) != len(selected_stages) or set(selected_stages) - {
            n["id"] for n in nodes
        }:
            raise StoryGenError("Select explicit existing pipeline stage IDs")
        nodes = [n for n in nodes if n["id"] in selected_stages]
    if historical_sources:
        from ..historical import HistoricalCatalog

        historical = HistoricalCatalog(depot)
        verified_runs = set()
        for port_key, selection in historical_sources.items():
            stage, port = port_key.split(".", 1)
            matches = [n for n in nodes if n["id"] == stage]
            if len(matches) != 1:
                raise StoryGenError("Historical input names an unselected stage")
            spec = registry.get(matches[0]["provider"]).capability(matches[0]["capability"])
            if port not in spec["inputs"]:
                raise StoryGenError("Historical input names an unknown port")
            run_id, relative = selection.split("@", 1)
            if run_id not in verified_runs:
                historical.verify(run_id)
                verified_runs.add(run_id)
            value = historical.port(run_id, relative, spec["inputs"][port]["semantic_type"])
            jsonschema.validate(value, spec["inputs"][port]["schema"])
            binding = matches[0].get("inputs", {}).get(port, {})
            producer = next((n for n in pipeline["nodes"] if n["id"] == binding.get("stage")), {})
            expected_strategy = producer.get("parameters", {}).get("strategy")
            if expected_strategy and value.get("strategy") != expected_strategy:
                raise StoryGenError(
                    "Historical condition differs from the declared upstream strategy"
                )
            source_values[port_key] = value
            source_provenance[port_key] = {
                "run_id": run_id,
                "receipt_sha256": historical.runs[run_id]["receipt_sha256"],
                "artifact_path": relative,
                "artifact_sha256": value["sha256"],
            }
    chosen = {n["id"] for n in nodes}
    for n in nodes:
        for name, binding in n.get("inputs", {}).items():
            if (
                binding.get("stage") not in chosen
                and "stage" in binding
                and n["id"] + "." + name not in source_values
            ):
                raise StoryGenError(
                    "Excluded upstream stage requires an exact historical --source: "
                    + n["id"]
                    + "."
                    + name
                )
    if definition["readiness"] not in {"READY", "TEST_ONLY"}:
        raise StoryGenError(
            f"{key}: {definition['readiness']}: {definition.get('blocker', 'faithful integration not verified')}; historical source remains available"
        )
    for node in nodes:
        spec = registry.get(node["provider"]).capability(node["capability"])
        if spec["nature"] == "historical":
            raise StoryGenError(
                "Historical algorithm adapter requires verified port binding before native execution"
            )
        registry.get(node["provider"]).load()
    tasks, pop = population(root, home, depot, definition)
    instruments = scientific.resolve_instruments(root, home, definition, depot)
    protocol = scientific.snapshot(home, definition, pipeline, instruments)
    role_definition = definition
    if selected_stages:
        required_roles = {n.get("model_role") for n in nodes}
        role_definition = {
            **definition,
            "model_roles": {
                k: v for k, v in definition["model_roles"].items() if k in required_roles
            },
        }
    resolved = scientific.resolve_conditions(role_definition, profile)
    if resolved:
        verify_profile(profile, resolved, hash_files=verify_files)
    if any(
        registry.get(n["provider"]).capability(n["capability"])["resources"].get("gpu")
        for n in nodes
    ):
        machine_coordination = (Path.home() / ".local/state/storygen").resolve()
        configured = (
            Path(profile.get("coordination_directory", machine_coordination)).expanduser().resolve()
        )
        if configured != machine_coordination:
            raise StoryGenError(
                "All profiles on this computer must share GPU coordination directory "
                + str(machine_coordination)
            )
    from .bindings import resolve

    pipeline_inputs = resolve(definition.get("bindings", {}), root, depot)
    for name, value in pipeline_inputs.items():
        if name not in pipeline.get("inputs", {}):
            raise StoryGenError("Binding names an undeclared pipeline input: " + name)
        jsonschema.validate(value, pipeline["inputs"][name]["schema"])
    for node in nodes:
        registry.get(node["provider"]).preflight(
            node["capability"], node=node, profile=profile, definition=definition
        )
    impl = scientific.implementation(root, registry, pipeline)
    if require_approval:
        scientific.approval(depot, impl)
    frozen = Path(depot) / "scientific_locks" / key / "lock.json"
    if frozen.exists() and read(frozen)["protocol_sha256"] != digest(protocol):
        raise StoryGenError("Frozen protocol drift; create a new scientific experiment ID")
    for node in nodes:
        spec = registry.get(node["provider"]).capability(node["capability"])
        role = node.get("model_role")
        if spec["nature"] == "inference" and (not role or role not in resolved):
            raise StoryGenError(f"Inference stage {node['id']} must bind a declared model role")
    return dict(
        home=home,
        definition=definition,
        pipeline=pipeline,
        nodes=nodes,
        tasks=tasks,
        population=pop,
        protocol=protocol,
        instruments=instruments,
        resolved=resolved,
        implementation=impl,
        pipeline_inputs=pipeline_inputs,
        source_values=source_values,
        historical_sources=historical_sources,
        source_provenance=source_provenance,
    )


class Context:
    def __init__(
        self,
        store,
        node,
        unit_id,
        attempt_id,
        profile,
        resolved,
        configuration,
        lock_hash,
        repair=False,
    ):
        self.store, self.node = store, deepcopy(node)
        self._stage_id = node["id"]
        self.unit_id, self.attempt_id = unit_id, attempt_id
        self.profile, self.resolved = deepcopy(profile), deepcopy(resolved)
        self.configuration = deepcopy(configuration)
        self.lock_hash, self.repair = lock_hash, repair
        self.raw_count = 0
        self.artifact_directory = (
            self.store.root / "native" / self._stage_id / self.unit_id / self.attempt_id
        )
        self.artifact_directory.mkdir(parents=True, exist_ok=True)

    def instrument(self, reference):
        protocol = read(self.store.root / "run.lock.json")["identity"]["protocol"]
        matches = [
            (i, item)
            for i, item in enumerate(protocol["instruments"])
            if reference in {item["path"], item.get("instrument_id")}
        ]
        if len(matches) != 1 or not matches[0][1].get("snapshot", True):
            raise StoryGenError("Instrument must resolve to one immutable critical snapshot")
        index, item = matches[0]
        path = self.store.root / "snapshot/instruments" / f"{index}-{Path(item['path']).name}"
        if not path.is_file() or file_sha(path) != item["sha256"]:
            raise StoryGenError("Scientific instrument snapshot missing or changed")
        return path

    def record_raw(self, response):
        self.raw_count += 1
        reference = self.store.data(self._stage_id, "raw", self.unit_id, self.attempt_id, response)
        self.store.events.append(
            "RAW_PERSISTED",
            stage_id=self._stage_id,
            unit_id=self.unit_id,
            attempt_id=self.attempt_id,
            reference=reference,
            lock_hash=self.lock_hash,
        )


def units(tasks, node):
    granularity = node["granularity"]
    if granularity == "TASK":
        return {t["task_id"]: [t] for t in tasks}
    if granularity == "DATASET":
        return {"dataset": tasks}
    if granularity == "FILM":
        groups = {}
        for task in tasks:
            if not task.get("film_id"):
                raise StoryGenError("FILM execution requires explicit film_id on every task")
            groups.setdefault(identifier(task["film_id"]), []).append(task)
        return dict(sorted(groups.items()))
    size = node.get("batch_size")
    if not isinstance(size, int) or size < 1:
        raise StoryGenError("BATCH execution requires a frozen positive batch_size")
    return {f"batch-{i // size:06}": tasks[i : i + size] for i in range(0, len(tasks), size)}


def run(
    root,
    depot,
    registry,
    key,
    profile,
    *,
    mode="dev",
    run_id=None,
    resume=False,
    task_ids=None,
    queue=False,
    crash_hook=None,
    catalog="experiments",
    selected_stages=None,
    historical_sources=None,
    manual_session=None,
):
    if run_id is not None and identifier(run_id).startswith("H-"):
        raise StoryGenError(
            "H- identifiers are reserved for historical imports; choose a new native run ID"
        )
    if mode not in {"dev", "scientific"}:
        raise StoryGenError("Mode must be dev or scientific")
    if selected_stages and mode != "dev":
        raise StoryGenError(
            "A partial pipeline is DEV only; frozen scientific execution requires its full pipeline"
        )
    selection_args = {}
    if selected_stages or historical_sources:
        selection_args = {
            "selected_stages": selected_stages,
            "historical_sources": historical_sources,
        }
    c = preflight(root, depot, registry, key, profile, catalog=catalog, **selection_args)
    if manual_session and not c["definition"].get("manual_server_session_allowed"):
        raise StoryGenError("This experiment does not allow an owned manual server session")
    if mode == "scientific" and c["definition"]["readiness"] == "TEST_ONLY":
        raise StoryGenError("TEST_ONLY examples cannot be promoted to scientific results")
    tasks = c["tasks"]
    if task_ids is not None:
        if mode != "dev":
            raise StoryGenError("Scientific task subsets require a separately defined experiment")
        if c["definition"].get("development_subset_policy") == "forbidden" and set(task_ids) != {
            t["task_id"] for t in tasks
        }:
            raise StoryGenError("This native protocol requires its complete frozen population")
        selected = set(task_ids)
        tasks = [t for t in tasks if t["task_id"] in selected]
        if len(tasks) != len(selected):
            raise StoryGenError("Unknown selected development task IDs")
    if not tasks:
        raise StoryGenError("Cannot run an empty population")
    for value in c.get("source_values", {}).values():
        if "task_count" in value and "path" in value:
            source_ids = {t["task_id"] for t in read(value["path"])["tasks"]}
            if source_ids != {t["task_id"] for t in tasks}:
                raise StoryGenError(
                    "Historical runtime tasks differ from selected DEV exposure; select an exact matching artifact"
                )
    if resume and not run_id:
        raise StoryGenError("Same-run resume requires the original run ID")
    run_id = identifier(run_id or ("R-" + uuid.uuid4().hex))
    root_run = Path(depot) / catalog / key / "runs" / run_id
    identity = {
        "catalog": catalog,
        "experiment_id": key,
        "run_id": run_id,
        "mode": mode,
        "protocol": c["protocol"],
        "implementation": c["implementation"],
        "conditions": c["resolved"],
        "profile": profile,
        "population": c["population"],
        "exposed_task_ids": [t["task_id"] for t in tasks] if mode == "dev" else [],
        "selected_task_ids": [t["task_id"] for t in tasks],
        "unit_plan": {n["id"]: list(units(tasks, n)) for n in c["nodes"]},
        "pipeline_input_references": c["definition"].get("bindings", {}),
    }
    lock_hash = digest(identity)
    if selected_stages or historical_sources:
        identity["selected_stages"] = selected_stages
        identity["historical_sources"] = historical_sources or {}
        identity["historical_input_values"] = c["source_values"]
        identity["historical_provenance"] = c["source_provenance"]
        lock_hash = digest(identity)
    if resume:
        if not (root_run / "run.lock.json").is_file():
            raise StoryGenError(f"Unknown immutable run: {run_id}")
        old = read(root_run / "run.lock.json")
        if old["identity"] != identity:
            raise StoryGenError("Resume code/model/conditions/input lock mismatch; begin a NEW run")
    else:
        from .common import durable_write, ensure_directory, sync_directory

        existing = [
            p
            for namespace in ("experiments", "analyses")
            for p in Path(depot).glob(f"{namespace}/*/runs/{run_id}")
        ]
        if existing:
            if root_run in existing:
                raise FileExistsError(
                    "Run ID already allocated; resume the SAME run or choose a new ID"
                )
            raise StoryGenError(
                "Run ID already used by another experiment; choose a globally unique ID"
            )
        try:
            write_json(
                Path(depot) / "run_ids" / (run_id + ".json"),
                {"run_id": run_id, "experiment_id": key, "reserved_utc": utc()},
            )
        except FileExistsError as exc:
            raise StoryGenError("Run ID is already reserved; choose a globally unique ID") from exc
        ensure_directory(root_run.parent)
        root_run.mkdir(exist_ok=False)
        sync_directory(root_run.parent)
        if mode == "scientific":
            scientific.freeze(depot, c["home"], c["protocol"], c["instruments"])
        # DEV snapshots preserve trial instruments independently without official freeze.
        snapshot_dir = root_run / "snapshot"
        ensure_directory(snapshot_dir)
        for name in ["experiment.yaml", "pipeline.yaml"]:
            durable_write(snapshot_dir / name, (c["home"] / name).read_bytes())
        for i, instrument in enumerate(c["instruments"]):
            source = Path(instrument["resolved_path"])
            if instrument.get("snapshot", True):
                if source.stat().st_size > 2 * 1024**2:
                    raise StoryGenError("DEV instrument too large for small critical snapshot")
                durable_write(
                    snapshot_dir / "instruments" / f"{i}-{source.name}", source.read_bytes()
                )
        write_json(
            root_run / "run.lock.json",
            {"identity": identity, "lock_sha256": lock_hash, "created_utc": utc()},
        )
    store = RunStore(root_run)
    needs_gpu = any(
        registry.get(n["provider"]).capability(n["capability"])["resources"].get("gpu")
        for n in c["nodes"]
    )
    coordination = Path(
        profile.get("coordination_directory", Path.home() / ".local/state/storygen")
    )
    if manual_session:
        from .manual_runtime import AttachedServer

        servers = AttachedServer(root, depot, profile, manual_session)
        lease = servers.lease()
    else:
        lease = gpu_lease(coordination, run_id, wait=queue) if needs_gpu else nullcontext()
        servers = ServerManager(profile, root_run / "runtime")
    interrupted = False
    with store.writer(), lease:
        store.validate_logs()
        accepted = store.committed(lock_hash)
        if resume:
            manifests = sorted(root_run.glob("evaluations/*.json"))
            if manifests and read(manifests[-1])["execution_status"] == "COMPLETE":
                raise StoryGenError("Completed run is immutable and cannot be resumed")
        store.events.append("RESUMED" if resume else "RUN_STARTED", lock_hash=lock_hash)
        failed = set()
        try:
            for node in c["nodes"]:
                provider = registry.get(node["provider"])
                spec = provider.capability(node["capability"])
                role = node.get("model_role")
                if historical_sources:
                    # External data is revalidated at every consuming stage, including resumes.
                    from ..historical import HistoricalCatalog

                    historical = HistoricalCatalog(depot)
                    for name in node.get("inputs", {}):
                        selection = historical_sources.get(node["id"] + "." + name)
                        if selection:
                            source_id = selection.split("@", 1)[0]
                            pinned = c["source_provenance"][node["id"] + "." + name]
                            if (
                                historical.runs[source_id]["receipt_sha256"]
                                != pinned["receipt_sha256"]
                            ):
                                raise StoryGenError(
                                    "Historical input receipt changed after run preflight"
                                )
                            historical.verify(source_id)
                pending_units = [
                    (uid, records)
                    for uid, records in units(tasks, node).items()
                    if (node["id"], uid) not in accepted
                ]
                if pending_units and spec["nature"] == "inference":
                    servers.switch(role)
                elif pending_units and servers.process is not None:
                    servers.stop()
                for uid, records in pending_units:
                    key_unit = (node["id"], uid)
                    bound, missing = {}, False
                    for name, port in spec["inputs"].items():
                        binding = node.get("inputs", {}).get(name)
                        if binding is None:
                            continue
                        source_key = node["id"] + "." + name
                        if source_key in c["source_values"]:
                            value = c["source_values"][source_key]
                        elif "input" in binding:
                            if binding["input"] in c["pipeline_inputs"]:
                                from .bindings import resolve

                                value = resolve(
                                    c["definition"]["bindings"][binding["input"]], root, depot
                                )
                            elif node["granularity"] == "TASK":
                                value = records[0].get(binding["input"])
                            else:
                                value = [
                                    t[binding["input"]] for t in records if binding["input"] in t
                                ]
                                if len(value) != len(records):
                                    value = None
                        else:
                            upstream = accepted.get((binding["stage"], uid), {})
                            value = upstream.get(binding["port"])
                        if value is None:
                            if port["required"]:
                                missing = True
                            continue
                        jsonschema.validate(value, port["schema"])
                        bound[name] = value
                    if missing:
                        failed.add(key_unit)
                        store.events.append(
                            "SKIPPED",
                            stage_id=node["id"],
                            unit_id=uid,
                            reason="missing required fan-in input; never imputed",
                            lock_hash=lock_hash,
                        )
                        continue
                    # Retry counters are rebuilt from prior durable attempts, including resumes.
                    history = [
                        e
                        for e in store.events.scan()
                        if e.get("stage_id") == node["id"] and e.get("unit_id") == uid
                    ]
                    transport = sum(e["kind"] == "TRANSPORT_FAILED" for e in history)
                    scientific_errors = sum(e["kind"] == "VALIDATION_FAILED" for e in history)
                    limits = c["definition"]["retries"]
                    while (
                        transport <= limits["transport"]
                        and scientific_errors <= limits["scientific"]
                    ):
                        attempt = uuid.uuid4().hex
                        store.events.append(
                            "STARTED",
                            stage_id=node["id"],
                            unit_id=uid,
                            attempt_id=attempt,
                            lock_hash=lock_hash,
                            recovery=bool(history),
                            input_sha256=digest(bound),
                        )
                        input_reference = store.data(node["id"], "inputs", uid, attempt, bound)
                        store.events.append(
                            "INPUT_PERSISTED",
                            stage_id=node["id"],
                            unit_id=uid,
                            attempt_id=attempt,
                            reference=input_reference,
                            lock_hash=lock_hash,
                        )
                        context = Context(
                            store,
                            node,
                            uid,
                            attempt,
                            profile,
                            c["resolved"],
                            node.get("parameters", {}),
                            lock_hash,
                            repair=scientific_errors > 0,
                        )
                        context.mode = mode
                        context.unit_members = deepcopy(records)
                        context.code_root = Path(root).resolve()
                        context.depot_root = Path(depot).resolve()
                        context.historical_sources = historical_sources or {}
                        context.managed_runtime = servers
                        try:
                            result = provider.load()(node["capability"], deepcopy(bound), context)
                            if spec["nature"] == "inference" and context.raw_count == 0:
                                raise ScientificResponseError(
                                    "Inference adapter did not durably preserve raw response"
                                )
                            if not isinstance(result, dict) or set(result) != set(spec["outputs"]):
                                raise ScientificResponseError(
                                    "Adapter output ports do not match contract"
                                )
                            for name, port in spec["outputs"].items():
                                jsonschema.validate(result[name], port["schema"])
                            if node.get("observations_port"):
                                observation = result[node["observations_port"]]
                                population_ids = observation["population_unit_ids"]
                                eligible_ids = observation["eligible_unit_ids"]
                                member_ids = {record["task_id"] for record in records}
                                if (
                                    len(set(population_ids)) != len(population_ids)
                                    or len(set(eligible_ids)) != len(eligible_ids)
                                    or not set(eligible_ids) <= set(population_ids)
                                    or not set(population_ids) <= member_ids
                                ):
                                    raise ScientificResponseError(
                                        "Native observation IDs differ from frozen unit membership"
                                    )
                            reference = store.data(node["id"], "outputs", uid, attempt, result)
                            store.events.append(
                                "OUTPUT_PERSISTED",
                                stage_id=node["id"],
                                unit_id=uid,
                                attempt_id=attempt,
                                reference=reference,
                                lock_hash=lock_hash,
                            )
                            if crash_hook:
                                crash_hook("OUTPUT_PERSISTED", node["id"], uid)
                            store.events.append(
                                "COMMITTED",
                                stage_id=node["id"],
                                unit_id=uid,
                                attempt_id=attempt,
                                reference=reference,
                                lock_hash=lock_hash,
                            )
                            accepted[key_unit] = result
                            break
                        except TransportError as exc:
                            transport += 1
                            store.events.append(
                                "TRANSPORT_FAILED",
                                stage_id=node["id"],
                                unit_id=uid,
                                attempt_id=attempt,
                                error=str(exc),
                                lock_hash=lock_hash,
                            )
                        except (ScientificResponseError, jsonschema.ValidationError) as exc:
                            scientific_errors += 1
                            store.events.append(
                                "VALIDATION_FAILED",
                                stage_id=node["id"],
                                unit_id=uid,
                                attempt_id=attempt,
                                error=str(exc),
                                lock_hash=lock_hash,
                            )
                        except (KeyboardInterrupt, InterruptedError):
                            raise
                        except Exception as exc:
                            store.events.append(
                                "FAILED",
                                stage_id=node["id"],
                                unit_id=uid,
                                attempt_id=attempt,
                                error=f"{type(exc).__name__}: {exc}",
                                lock_hash=lock_hash,
                            )
                            break
                    if key_unit not in accepted:
                        failed.add(key_unit)
                stage_values = {
                    uid: value for (stage, uid), value in accepted.items() if stage == node["id"]
                }
                revision = len(list((root_run / "stages" / node["id"]).glob("manifest-*.json"))) + 1
                write_json(
                    root_run / "stages" / node["id"] / f"manifest-{revision:06}.json",
                    {
                        "stage_id": node["id"],
                        "provider": provider.pin(),
                        "granularity": node["granularity"],
                        "expected": len(units(tasks, node)),
                        "committed": len(stage_values),
                        "outputs_sha256": digest(stage_values),
                        "utc": utc(),
                    },
                )
        except (KeyboardInterrupt, InterruptedError):
            interrupted = True
            store.events.append("INTERRUPTED", lock_hash=lock_hash)
        finally:
            servers.stop()
        expected_keys = {(n["id"], uid) for n in c["nodes"] for uid in units(tasks, n)}
        valid = len(expected_keys & set(accepted))
        errors = len(expected_keys - set(accepted))
        task_valid = sum(
            all(
                (n["id"], uid) in accepted
                for n in c["nodes"]
                for uid, members in units(tasks, n).items()
                if any(member["task_id"] == task["task_id"] for member in members)
            )
            for task in tasks
        )
        technical_task_valid = task_valid
        observations = []
        eligible = {task["task_id"] for task in tasks}
        for node in c["nodes"]:
            port = node.get("observations_port")
            if port is None:
                continue
            node_eligible = set()
            node_population = set()
            for uid in units(tasks, node):
                value = accepted.get((node["id"], uid), {}).get(port)
                if value is None:
                    continue
                population_ids = set(value["population_unit_ids"])
                eligible_ids = set(value["eligible_unit_ids"])
                if not eligible_ids <= population_ids or not population_ids <= {
                    task["task_id"] for task in tasks
                }:
                    raise StoryGenError(
                        "Native observation IDs differ from selected frozen population"
                    )
                node_population.update(population_ids)
                node_eligible.update(eligible_ids)
            eligible.intersection_update(node_eligible)
            observations.append(
                {
                    "stage_id": node["id"],
                    "observed_units": len(node_population),
                    "eligible_units": len(node_eligible),
                    "population_units": len(tasks),
                }
            )
        if observations:
            task_valid = min(task_valid, len(eligible))
        assessment = scientific.gates(c["definition"], task_valid, len(tasks), errors)
        for node in c["nodes"]:
            port = node.get("native_checks_port")
            if port is None:
                continue
            for uid in units(tasks, node):
                checks = accepted.get((node["id"], uid), {}).get(port)
                if checks is None:
                    assessment["checks"].append(
                        {
                            "name": node["id"] + ":" + uid,
                            "status": "FAIL",
                            "reason": "Native scientific validation missing",
                        }
                    )
                else:
                    assessment["checks"].extend(
                        {
                            **check,
                            "stage_id": node["id"],
                            "unit_id": uid,
                            "origin": "original_scientific_validator",
                        }
                        for check in checks["checks"]
                    )
        if any(check["status"] != "PASS" for check in assessment["checks"]):
            assessment["status"] = "FAIL"
        result = {
            "experiment_id": key,
            "run_id": run_id,
            "mode": mode,
            "execution_status": "INTERRUPTED"
            if interrupted
            else ("COMPLETE" if not errors else "PARTIAL"),
            "scientific_gate": assessment,
            "scientific_results_verified": False,
            "completed_units": valid,
            "expected_units": len(expected_keys),
            "task_population": len(tasks),
            "valid_tasks": task_valid,
            "technically_completed_tasks": technical_task_valid,
            "native_observations": observations,
            "eligible_condition_observations": sum(v["eligible_units"] for v in observations)
            if observations
            else None,
            "runtime": servers.actual,
            "lock_sha256": lock_hash,
            "finished_utc": utc(),
            "development_exposure": identity["exposed_task_ids"],
            "remote_backup": "NOT_REQUESTED",
        }
        number = len(list((root_run / "evaluations").glob("*.json"))) + 1
        write_json(root_run / "evaluations" / f"{number:06}.json", result)
        store.events.append(
            "ASSESSMENT",
            execution_status=result["execution_status"],
            evaluation=f"evaluations/{number:06}.json",
            lock_hash=lock_hash,
        )
        return root_run, result
