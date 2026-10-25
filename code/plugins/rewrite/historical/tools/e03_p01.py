"""Offline P01: verify historical authorities, freeze performance-blind selection.

No server/contact/inference; paths supplied explicitly by E03 CLI.
"""
from pathlib import Path
import json, sys, hashlib, subprocess
from datetime import datetime, timezone
from collections import Counter, defaultdict
import numpy as np
from e02_min import read, write, sha, checked, git, imports

def prepare_selection(workspace, plan_path, before_path):
    w = Path(workspace)
    imports(w)
    from storygen_evaluation.provenance import validate_reference, validate_runtime, ArtifactResolver, structure_sha, validate_curves
    from storygen_measurement_core import MeasurementProtocol
    from storygen.rewrite_v1_3.provenance import prompt_provenance, sha256_json
    from storygen.schemas.transfer import TransferPlan
    from storygen.services.transfer_planner import create_transfer_plan_from_feature_files
    from storygen.services.rewrite_engine import load_selected_scenes
    from storygen.services import per_scene_rewrite_engine as e
    from storygen.services.vllm_client import _messages
    before = read(before_path)
    plan = read(plan_path)
    ts = checked(plan['taskset'])
    ref = checked(plan['reference_feature_set'])
    overrides = checked(plan['artifact_overrides'])
    validate_reference(ref)
    validate_runtime(ts, ref, Path(plan['reference_feature_set']['path']), ArtifactResolver(overrides))
    if not structure_sha(ts['tasks']) == 'sha256:840aafe93408d41f3ef2e8fe791b0401ce52008060031a58aa46e4e28944bcdb':
        raise RuntimeError("E03 P01 invariant failed: structure_sha(ts['tasks']) == 'sha256:840aafe93408d41f3ef2e8fe791b0401ce52008060031a58aa46e4e28944bcdb'")
    if not len(ts['tasks']) == 240:
        raise RuntimeError("E03 P01 invariant failed: len(ts['tasks']) == 240")
    controls = [c for c in plan['runs'] if c['display_model'] == 'Gemma-3-12B']
    old = {c['condition']: checked(c['rewrite_manifest']) for c in controls}
    if not set(old) == {'CG-v1', 'DP-v1'}:
        raise RuntimeError("E03 P01 invariant failed: set(old) == {'CG-v1', 'DP-v1'}")
    a, b = old.values()
    if not (a['model'] == b['model'] and a['server_manifest']['content'] == b['server_manifest']['content'] and (a['decoding'] == b['decoding'] == dict(temperature=0.2, max_tokens=4096, schema_retry_count=1, concurrency=4, timeout_seconds=900))):
        raise RuntimeError("E03 P01 invariant failed: a['model'] == b['model'] and a['server_manifest']['content'] == b['server_manifest']['content'] and (a['decoding'] == b['decoding'] == dict(temperature=0.2, max_tokens=4096, schema_retry_count=1, concurrency=4, timeout_seconds=900))")
    protocol = MeasurementProtocol.load(w / 'storygen-feature-extraction/measurement', 'configs/feature_measurement_v1.yaml')
    if not protocol.manifest() == ref['measurement']:
        raise RuntimeError("E03 P01 invariant failed: protocol.manifest() == ref['measurement']")
    servers = {'gemma': a['server_manifest']['content'], 'qwen': ref['runtime_identity']['server']}
    models = {}
    for key, s in servers.items():
        expected = 'sha256:' + s['model_sha256'].removeprefix('sha256:')
        if not sha(s['model_path']) == expected:
            raise RuntimeError("E03 P01 invariant failed: sha(s['model_path']) == expected")
        models[key] = dict(path=s['model_path'], sha256=expected)
        print('Checkpoint verified:', key, flush=True)
    if a['model']['file_sha256'] != models['gemma']['sha256'] or a['model']['exact_file'] != models['gemma']['path'] or a['model']['served_alias'] != servers['gemma']['model_alias'] or a['model']['quantization'] != servers['gemma']['quantization']:
        raise RuntimeError('Historical checkpoint/model/server identity disagreement')
    if protocol.model['model_sha256'] != models['qwen']['sha256'] or protocol.model['checkpoint_path'] != models['qwen']['path']:
        raise RuntimeError('Original Qwen protocol/checkpoint identity disagreement')
    if not (servers['gemma']['parallel_slots'], servers['gemma']['context_per_slot'], servers['qwen']['parallel_slots'], servers['qwen']['context_per_slot']) == (4, 12288, 8, 12288):
        raise RuntimeError("E03 P01 invariant failed: (servers['gemma']['parallel_slots'], servers['gemma']['context_per_slot'], servers['qwen']['parallel_slots'], servers['qwen']['context_per_slot']) == (4, 12288, 8, 12288)")
    binary = servers['gemma']['server_binary']
    commit = servers['gemma']['llama_cpp_commit']
    if not (servers['qwen']['server_binary'] == binary and servers['qwen']['llama_cpp_commit'] == commit == git(w / 'llama.cpp', 'rev-parse', 'HEAD')):
        raise RuntimeError("E03 P01 invariant failed: servers['qwen']['server_binary'] == binary and servers['qwen']['llama_cpp_commit'] == commit == git(w / 'llama.cpp', 'rev-parse', 'HEAD')")
    v = subprocess.run([binary, '--version'], capture_output=True, text=True, check=True)
    if not commit[:9] in v.stdout + v.stderr:
        raise RuntimeError('E03 P01 invariant failed: commit[:9] in v.stdout + v.stderr')
    for c in controls:
        m = old[c['condition']]
        if m['feature_set_manifest']['sha256'] != plan['reference_feature_set']['sha256'] or m['feature_set_manifest']['measurement'] != ref['measurement']:
            raise RuntimeError('Historical rewrite/reference full Qwen lineage mismatch')
        hist = Path(overrides.get(m['taskset']['path'], m['taskset']['path']))
        if not (sha(hist) == m['taskset']['sha256'] and structure_sha(read(hist)['tasks']) == structure_sha(ts['tasks'])):
            raise RuntimeError("E03 P01 invariant failed: sha(hist) == m['taskset']['sha256'] and structure_sha(read(hist)['tasks']) == structure_sha(ts['tasks'])")
        pp = prompt_provenance(w / 'storygen-rewrite/rewrite', c['condition'])
        if not all((pp[k]['sha256'] == m['prompt_provenance'][k]['sha256'] for k in ('user_prompt', 'system_prompt', 'repair_prompt', 'method_config'))):
            raise RuntimeError("E03 P01 invariant failed: all((pp[k]['sha256'] == m['prompt_provenance'][k]['sha256'] for k in ('user_prompt', 'system_prompt', 'repair_prompt', 'method_config')))")
    from storygen.rewrite_v1_3.repeatability import select_tasks, SELECTION_FIELDS
    chosen, trial_count = select_tasks(ts['tasks'])
    selected, sub = (chosen['CG-v1'], chosen['DP-v1'])
    trial = trial_count - 1
    fields = SELECTION_FIELDS
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    roots = {k: w / (r + '-depot') / 'runs/reviewer_round1/E03_generation_repeatability' / stamp for k, r in [('rewrite', 'storygen-rewrite'), ('feature', 'storygen-feature-extraction'), ('evaluation', 'storygen-evaluation')]}
    for p in roots.values():
        p.mkdir(parents=True, exist_ok=False)
    root = roots['rewrite']
    write(root / 'manifests/BEFORE_CHANGES.json', before)
    bound = json.loads(json.dumps(ts))
    bound['feature_set_manifest'] = plan['reference_feature_set']['path']
    for task in bound['tasks']:
        script = w / 'storygen-feature-extraction-depot/runs/_inputs/films' / task['source_film_id'] / 'script.json'
        filmroot = Path(plan['reference_feature_set']['path']).parent / 'films' / task['source_film_id']
        if not read(filmroot / 'measurement_manifest.json')['script_sha256'] == sha(script):
            raise RuntimeError("E03 P01 invariant failed: read(filmroot / 'measurement_manifest.json')['script_sha256'] == sha(script)")
        task['source_script_path'] = str(script)
        for side in ('source', 'reference'):
            task[side + '_feature_path'] = str(Path(plan['reference_feature_set']['path']).parent / 'films' / task[side + '_film_id'] / 'scene_features_llm.json')
    if not structure_sha(bound['tasks']) == structure_sha(ts['tasks']):
        raise RuntimeError("E03 P01 invariant failed: structure_sha(bound['tasks']) == structure_sha(ts['tasks'])")
    validate_runtime(bound, ref, Path(plan['reference_feature_set']['path']), ArtifactResolver())
    write(root / 'inputs/PARENT_RUNTIME_240.json', bound)
    selection = dict(contract='storygen.E03.selection/1.0', seed=4203, rng='numpy.random.default_rng / PCG64', metadata_fields=list(fields), performance_blind=True, method='Shuffle sorted 48 base IDs and 48 axis labels (sorted five axes repeated, first 48); select corresponding axis task. Continue same RNG, first 4-per-length subset with feature counts 2/2/2/3/3 and all 10 source films.', matched_trials=trial + 1, frozen_parent=plan['taskset'], parent_structure_sha256=structure_sha(ts['tasks']), conditions={})
    prompts = []
    plans = {}
    for condition, chosen in [('CG-v1', selected), ('DP-v1', sub)]:
        ids = [t['task_id'] for t in chosen]
        tasks = [t for t in bound['tasks'] if t['task_id'] in ids]
        if not [t['task_id'] for t in tasks] == ids:
            raise RuntimeError("E03 P01 invariant failed: [t['task_id'] for t in tasks] == ids")
        projection = {**bound, 'tasks': tasks, 'structure_sha256': structure_sha(tasks), 'e03_parent_taskset': plan['taskset'], 'e03_projection': 'execution-only selection; original scientific TasksetV5 unchanged'}
        write(root / f'inputs/{condition}_RUNTIME.json', projection)
        selection['conditions'][condition] = dict(task_ids=ids, task_count=len(tasks), repetitions=5, features=dict(Counter((t['selected_features'][0] for t in tasks))), lengths=dict(Counter((t['interval_type'] for t in tasks))), source_films=dict(Counter((t['source_film_id'] for t in tasks))), scene_positions_per_repeat=sum((len(t['source_scene_ids']) for t in tasks)))
        for task in tasks:
            tid = task['task_id']
            frozen = []
            for c in controls:
                p = Path(c['rewrite_manifest']['path']).parent / 'tasks' / tid / 'transfer_plan.json'
                hp = read(p)
                hp['feature_source_path'] = task['source_feature_path']
                hp['reference_feature_source_path'] = task['reference_feature_path']
                frozen.append(hp)
            if not frozen[0] == frozen[1]:
                raise RuntimeError('E03 P01 invariant failed: frozen[0] == frozen[1]')
            canonical = create_transfer_plan_from_feature_files(**{k: task[k] for k in ('source_feature_path', 'reference_feature_path', 'source_start_scene_id', 'source_end_scene_id', 'reference_start_scene_id', 'reference_end_scene_id', 'selected_features')}, run_id=tid).model_dump(mode='json')
            if not canonical == frozen[0]:
                raise RuntimeError('Historical transfer plan differs: ' + tid)
            write(root / f'inputs/frozen_plans/tasks/{tid}/transfer_plan.json', frozen[0])
            plans[tid] = frozen[0]
            transfer = TransferPlan.model_validate(frozen[0])
            scenes = load_selected_scenes(task['source_script_path'], task['source_scene_ids'])
            system = (w / 'storygen-rewrite/rewrite/prompts' / ('curve_guided_system_v1.txt' if condition == 'CG-v1' else 'direct_prompt_system_v1.txt')).read_text()
            builder = e.build_per_scene_rewrite_prompt if condition == 'CG-v1' else e.build_per_scene_direct_prompt
            for i, (scene, directive) in enumerate(zip(scenes, transfer.per_scene_target_values)):
                user = builder(scene=scene, directive=directive, plan=transfer, scene_position_index=i, scene_count=len(scenes), max_scene_chars=12000)
                payload = dict(model=servers['gemma']['model_alias'], messages=_messages(system=system, prompt=user, model=servers['gemma']['model_alias'], structured=True), stream=False, temperature=0.2, max_tokens=4096, response_format=dict(type='json_schema', json_schema=dict(name='storygen_response', strict=True, schema=e.one_scene_rewrite_schema_for(scene.scene_id))))
                prompts.append(dict(condition=condition, task_id=tid, base_interval_id=task['base_interval_id'], scene_id=scene.scene_id, prompt_hash=sha256_json(payload['messages']), request_contract_hash=sha256_json(payload), payload=payload, source_characters=len(scene.content), historical_12000_character_cap_applied=len(scene.content) > 12000))
    if not (selection['conditions']['CG-v1']['scene_positions_per_repeat'] == 400 and selection['conditions']['DP-v1']['scene_positions_per_repeat'] == 100):
        raise RuntimeError("E03 P01 invariant failed: selection['conditions']['CG-v1']['scene_positions_per_repeat'] == 400 and selection['conditions']['DP-v1']['scene_positions_per_repeat'] == 100")
    validate_curves([t for t in bound['tasks'] if t['task_id'] in plans], root / 'inputs/frozen_plans', root / 'inputs/frozen_plans', Path(plan['reference_feature_set']['path']), ref, ArtifactResolver())
    write(root / 'manifests/SELECTION.json', selection)
    write(root / 'inputs/PRIMARY_REQUESTS.json', prompts)
    for key, s in servers.items():
        write(root / f'manifests/{key.upper()}_SERVER.json', s)
    seedfiles = [w / 'llama.cpp/tools/server/server-schema.cpp', w / 'llama.cpp/tools/server/server-task.cpp', w / 'llama.cpp/tools/server/server-common.cpp', w / 'llama.cpp/tools/server/server-context.cpp', w / 'storygen-rewrite/rewrite/src/storygen/services/vllm_client.py']
    write(root / 'manifests/SEED_SUPPORT.json', dict(backend_commit=commit, evidence={str(p): sha(p) for p in seedfiles}, transport='_translate_options direct_keys includes seed; payload.update translates into /v1/chat/completions JSON', backend='server-schema.cpp field_num seed maps to params.sampling.seed; server-task.cpp serializes sampling.seed', status='SUPPORTED_OFFLINE_VERIFIED'))
    write(root / 'P01.json', dict(P01='PASS', roots={k: str(p) for k, p in roots.items()}, selection=selection, plan_path=before['plan_path'], reference=plan['reference_feature_set'], parent=plan['taskset'], controls=controls, models=models, servers=servers, measurement=protocol.manifest(), decoding=a['decoding'], binary_sha256=sha(binary), scientific_results='NOT_RUN'))
    print('P01 PASS:', root)
    print(json.dumps(selection['conditions'], indent=2))
    print('Matched selection trials:', trial + 1)
    return root
