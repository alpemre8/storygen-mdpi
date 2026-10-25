"""E02-MIN preparation (offline) and explicitly invoked author-run stages.

Usage: python tools/e02_min.py prepare --workspace ... --plan ...
       python tools/e02_min.py preflight|server-gemma|stage-a|server-qwen|stage-c|stage-d --run ...
Preparation never calls a server or generates experimental measurements.
"""
from __future__ import annotations
from .technical import checked, context_check, live_runtime, read, server_command, sha, write
from .bindings import REWRITE, imports, git
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

def prepare(workspace, plan_path):
    imports(workspace)
    from storygen_measurement_core import MeasurementProtocol
    from storygen_measurement_core.preflight import assert_measurement_equal
    from storygen.services.rewrite_engine import load_selected_scenes
    from storygen.services.per_scene_rewrite_engine import build_per_scene_no_guidance_prompt
    from storygen.services.transfer_planner import create_transfer_plan_from_feature_files
    from storygen.rewrite_v1_3.no_guidance import group_tasks
    from storygen.rewrite_v1_3.provenance import prompt_provenance, recursive_keys
    from storygen_evaluation.metrics import measurement_identity
    from storygen_evaluation.provenance import validate_reference, validate_runtime, structure_sha, ArtifactResolver, validate_curves, same_provenance
    from storygen_evaluation.ng_baseline import prepare_tables
    plan = read(plan_path)
    taskset = checked(plan['taskset'])
    reference = checked(plan['reference_feature_set'])
    overrides = checked(plan['artifact_overrides'])
    validate_reference(reference)
    validate_runtime(taskset, reference, Path(plan['reference_feature_set']['path']), ArtifactResolver(overrides))
    controls = [r for r in plan['runs'] if r['display_model'] == 'Gemma-3-12B']
    if {c['condition'] for c in controls} != {'DP-v1', 'CG-v1'} or len(controls) != 2:
        raise RuntimeError('Both frozen Gemma controls are required')
    for control in controls:
        for key in ('rewrite_manifest', 'reanalysis_manifest', 'records', 'evaluation_manifest'):
            if sha(control[key]['path']) != control[key]['sha256']:
                raise RuntimeError('Historical control SHA mismatch')
    old = [checked(c['rewrite_manifest']) for c in controls]
    evaluations = [checked(c['evaluation_manifest']) for c in controls]
    same_provenance(evaluations, artifact_paths=overrides)
    if any((m['measurement_identity'] != measurement_identity(reference['measurement']) for m in evaluations)):
        raise RuntimeError('Historical evaluation Qwen identity mismatch')
    if old[0]['model'] != old[1]['model'] or old[0]['decoding'] != old[1]['decoding'] or old[0]['server_manifest']['content'] != old[1]['server_manifest']['content']:
        raise RuntimeError('Historical Gemma runtime disagreement')
    if old[0]['decoding'] != dict(temperature=0.2, max_tokens=4096, schema_retry_count=1, concurrency=4, timeout_seconds=900):
        raise RuntimeError('Historical Gemma decoding mismatch')
    protocol = MeasurementProtocol.load(workspace / 'storygen-feature-extraction/measurement', 'configs/feature_measurement_v1.yaml')
    assert_measurement_equal(reference['measurement'], protocol.manifest())
    if protocol.manifest() != reference['measurement']:
        raise RuntimeError('Full frozen Qwen measurement contract mismatch')
    gemma = old[0]['server_manifest']['content']
    qwen = reference['runtime_identity']['server']
    if (gemma['parallel_slots'], gemma['context_per_slot'], qwen['parallel_slots'], qwen['context_per_slot']) != (4, 12288, 8, 12288):
        raise RuntimeError('Historical server/context profile mismatch')
    models = {key: dict(path=server['model_path'], sha256='sha256:' + server['model_sha256'].removeprefix('sha256:')) for key, server in [('gemma', gemma), ('qwen', qwen)]}
    for key, ref in models.items():
        if sha(ref['path']) != ref['sha256']:
            raise RuntimeError('Local checkpoint SHA mismatch: ' + key)
    binary = Path(gemma['server_binary'])
    if qwen['server_binary'] != str(binary) or git(workspace / 'llama.cpp', 'rev-parse', 'HEAD') != gemma['llama_cpp_commit'] or qwen['llama_cpp_commit'] != gemma['llama_cpp_commit']:
        raise RuntimeError('Backend build identity mismatch')
    version = subprocess.run([str(binary), '--version'], capture_output=True, text=True, check=True)
    if gemma['llama_cpp_commit'][:9] not in version.stdout + version.stderr:
        raise RuntimeError('Backend binary version mismatch')
    paths = {}
    bound = json.loads(json.dumps(taskset))
    for task in bound['tasks']:
        script = workspace / 'storygen-feature-extraction-depot/runs/_inputs/films' / task['source_film_id'] / 'script.json'
        film_root = Path(plan['reference_feature_set']['path']).parent / 'films' / task['source_film_id']
        if read(film_root / 'measurement_manifest.json')['script_sha256'] != sha(script):
            raise RuntimeError('Original script/Qwen measurement identity mismatch')
        paths[task['source_script_path']] = script
        task['source_script_path'] = str(script)
        for side in ('source', 'reference'):
            task[side + '_feature_path'] = str(Path(plan['reference_feature_set']['path']).parent / 'films' / task[side + '_film_id'] / 'scene_features_llm.json')
    units = group_tasks(taskset['tasks'], paths)
    if structure_sha(bound['tasks']) != structure_sha(taskset['tasks']):
        raise RuntimeError('Source binding changed frozen task identities')
    for control, manifest in zip(controls, old):
        recorded = manifest['taskset']['path']
        resolved = Path(overrides.get(recorded, recorded))
        if sha(resolved) != manifest['taskset']['sha256'] or structure_sha(read(resolved)['tasks']) != structure_sha(taskset['tasks']):
            raise RuntimeError('Historical generation taskset identity mismatch')
        provenance = prompt_provenance(REWRITE / 'rewrite', control['condition'])
        if any((provenance[k]['sha256'] != manifest['prompt_provenance'][k]['sha256'] for k in ('user_prompt', 'system_prompt', 'repair_prompt', 'method_config'))):
            raise RuntimeError('Historical DP/CG prompt assets changed')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    roots = {key: workspace / (repo + '-depot') / 'runs/reviewer_round1/E02_MIN_ng_v0' / stamp for key, repo in [('rewrite', 'storygen-rewrite'), ('feature', 'storygen-feature-extraction'), ('evaluation', 'storygen-evaluation')]}
    for root in roots.values():
        root.mkdir(parents=True, exist_ok=False)
    root = roots['rewrite']
    manifest_dir = root / 'manifests'
    manifest_dir.mkdir()
    bound['feature_set_manifest'] = plan['reference_feature_set']['path']
    bound['structure_sha256'] = structure_sha(taskset['tasks'])
    write(root / 'inputs/TASKSET_240.json', bound)
    write(root / 'inputs/BASE_TO_TASKS.json', dict(contract='storygen.ng-base-mapping/1.0', generation_units=48, planned_scene_requests=400, evaluation_tasks=240, frozen_taskset=plan['taskset'], units=units))
    base_tasks = [dict(task_id=u['base_interval_id'], base_interval_id=u['base_interval_id'], source_film_id=u['source_film_id'], source_script_path=u['source_script_path'], source_scene_ids=u['source_scene_ids'], evaluation_task_ids=u['task_ids'], selected_features=[]) for u in units]
    write(root / 'inputs/BASE_RUNTIME_48.json', dict(contract='storygen.ng-base-runtime/1.0', feature_set_id=reference['feature_set_id'], frozen_taskset=plan['taskset'], tasks=base_tasks))
    hidden = roots['evaluation'] / 'inputs/hidden_plans/tasks'
    for task in bound['tasks']:
        transfer = create_transfer_plan_from_feature_files(**{k: task[k] for k in ('source_feature_path', 'reference_feature_path', 'source_start_scene_id', 'source_end_scene_id', 'reference_start_scene_id', 'reference_end_scene_id', 'selected_features')}, run_id=task['task_id'])
        if transfer.source_scene_ids != task['source_scene_ids'] or transfer.reference_scene_ids != task['reference_scene_ids']:
            raise RuntimeError('Canonical hidden transfer-plan selection mismatch')
        write(hidden / task['task_id'] / 'transfer_plan.json', transfer.model_dump(mode='json'))
    validate_curves(bound['tasks'], hidden.parent, hidden.parent, Path(plan['reference_feature_set']['path']), reference, ArtifactResolver())
    prompt_checks = []
    forbidden = {'selected_features', 'selected_rewrite_aspects', 'current_values', 'targets', 'target_values', 'deltas', 'reference_curve', 'reference_scene_ids', 'reference_film_id', 'reference_interval_scene_ids', 'directive'}
    for unit in units:
        scenes = load_selected_scenes(unit['source_script_path'], unit['source_scene_ids'])
        for index, scene in enumerate(scenes):
            prompt = build_per_scene_no_guidance_prompt(scene=scene, scene_position_index=index, scene_count=len(scenes))
            if recursive_keys(json.loads(prompt)) & forbidden:
                raise RuntimeError('Forbidden NG prompt keys')
            prompt_checks.append(dict(base_interval_id=unit['base_interval_id'], scene_id=scene.scene_id, user_sha256='sha256:' + hashlib.sha256(prompt.encode()).hexdigest()))
    write(manifest_dir / 'PROMPT_CHECKS.json', dict(planned_prompts=len(prompt_checks), forbidden_key_leaks=0, prompt_provenance=prompt_provenance(REWRITE / 'rewrite', 'NG-v0'), checks=prompt_checks))
    write(manifest_dir / 'GEMMA_SERVER.json', gemma)
    write(manifest_dir / 'QWEN_SERVER.json', qwen)
    protected = {str(plan_path): sha(plan_path), **{str(x): sha(x) for x in paths.values()}}
    for control in controls:
        for key in ('rewrite_manifest', 'reanalysis_manifest', 'evaluation_manifest'):
            for file in Path(control[key]['path']).parent.rglob('*'):
                if file.is_file():
                    protected[str(file)] = sha(file)
    for file in Path(plan['reference_feature_set']['path']).parent.rglob('*'):
        if file.is_file():
            protected[str(file)] = sha(file)
    for ref in (plan['taskset'], plan['artifact_overrides'], plan['p01a_gate'], plan['approved_a6_protocol']):
        checked(ref)
        protected[ref['path']] = ref['sha256']
    source_commits = {}
    for repo in ('storygen-rewrite', 'storygen-feature-extraction', 'storygen-evaluation'):
        path = workspace / repo
        source_commits[repo] = git(path, 'rev-parse', 'HEAD')
        for name in git(path, 'ls-files').splitlines():
            file = path / name
            if file.is_file():
                protected[str(file)] = sha(file)
    for base in (root / 'inputs', roots['evaluation'] / 'inputs', manifest_dir):
        for file in base.rglob('*'):
            if file.is_file():
                protected[str(file)] = sha(file)
    protected[str(binary)] = sha(binary)
    config = dict(contract='storygen.E02-MIN/1.0', workspace=str(workspace), roots={k: str(v) for k, v in roots.items()}, frozen_taskset=plan['taskset'], reference=plan['reference_feature_set'], controls=controls, models=models, structure_sha256=structure_sha(taskset['tasks']), measurement=protocol.manifest(), base_tasks=base_tasks, mapping=str(root / 'inputs/BASE_TO_TASKS.json'), bound_taskset=str(root / 'inputs/TASKSET_240.json'), base_runtime=str(root / 'inputs/BASE_RUNTIME_48.json'), hidden_plans=str(hidden), gemma_server=gemma, qwen_server=qwen, gemma_manifest=str(manifest_dir / 'GEMMA_SERVER.json'), qwen_manifest=str(manifest_dir / 'QWEN_SERVER.json'), source_commits=source_commits, rewrite_output=str(root / 'outputs/NG-v0'), measurement_output=str(roots['feature'] / 'outputs/ng_v0_fev1_4'), evaluation_output=str(roots['evaluation'] / 'outputs/T02_A03'), protected=protected)
    write(root / 'CONFIG.json', config)
    (root / 'CONFIG.sha256').write_text(sha(root / 'CONFIG.json') + '\n')
    prepare_tables(roots['evaluation'] / 'prepared_tables')
    write(manifest_dir / 'OFFLINE_GATES.json', dict(P01='PASS', P02='see offline test log', P03='PASS', implementation_status='IMPLEMENTATION_READY', execution_status='HUMAN_RUN_PENDING', scientific_results='NOT_RUN', task_count=240, base_intervals=48, scene_positions=400, forbidden_prompt_leaks=0, historical_fingerprints=len(protected), truncated_positions=sum((len(u['truncated_scene_ids']) for u in units))))
    for key, other in roots.items():
        if key != 'rewrite':
            write(other / 'PREPARATION_LINK.json', dict(config=str(root / 'CONFIG.json'), main_report=str(root / 'PREPARATION_REPORT.md')))
    print(root)
    return root

def load_config(run):
    if sha(run / 'CONFIG.json') != (run / 'CONFIG.sha256').read_text().strip():
        raise RuntimeError('E02 configuration seal mismatch')
    config = read(run / 'CONFIG.json')
    workspace = Path(config['workspace'])
    imports(workspace)
    for path, expected in config['protected'].items():
        if sha(path) != expected:
            raise RuntimeError('Frozen/protected artifact changed: ' + path)
    for repo, commit in config['source_commits'].items():
        if git(workspace / repo, 'rev-parse', 'HEAD') != commit:
            raise RuntimeError('Source commit changed: ' + repo)
    for ref in config['models'].values():
        if sha(ref['path']) != ref['sha256']:
            raise RuntimeError('Checkpoint identity changed')
    return config

def execute(action, run):
    config = load_config(run)
    if action == 'preflight':
        print('P01/P03 offline preflight PASS; inference NOT_RUN')
        return
    if action.startswith('server-'):
        key = action.removeprefix('server-')
        server = config[key + '_server']
        record = run / 'runtime' / ('SERVER_' + key.upper() + '.json')
        record.parent.mkdir(exist_ok=True)
        with record.open('x') as handle:
            json.dump(dict(pid=os.getpid(), command=server_command(server), model=config['models'][key]), handle)
        log = run / 'logs' / ('SERVER_' + key.upper() + '.log')
        log.parent.mkdir(exist_ok=True)
        with log.open('xb') as handle:
            os.dup2(handle.fileno(), 2)
        print('Starting persistent ' + key + ' server; logs: ' + str(log), flush=True)
        env = {k: v for k, v in os.environ.items() if not k.startswith('LLAMA_ARG_')}
        os.execve(server['server_binary'], server_command(server), env)
    if action == 'stage-a':
        from storygen.rewrite_v1_3.no_guidance import run_ng
        from storygen.services.rewrite_engine import load_selected_scenes
        from storygen.services.per_scene_rewrite_engine import build_per_scene_no_guidance_prompt
        from storygen.services.per_scene_rewrite_engine import one_scene_rewrite_schema_for
        from storygen.services.vllm_client import _messages
        system = (REWRITE / 'rewrite/prompts/no_guidance_system_v0.txt').read_text()
        url = live_runtime(config, 'gemma')
        prompts = []
        for unit in read(config['mapping'])['units']:
            scenes = load_selected_scenes(unit['source_script_path'], unit['source_scene_ids'])
            for i, scene in enumerate(scenes):
                user = build_per_scene_no_guidance_prompt(scene=scene, scene_position_index=i, scene_count=len(scenes))
                prompts.append(dict(model=config['gemma_server']['model_alias'], stream=False, temperature=0.2, max_tokens=4096, messages=_messages(system=system, prompt=user, model=config['gemma_server']['model_alias'], structured=True), response_format={'type': 'json_schema', 'json_schema': {'name': 'storygen_response', 'strict': True, 'schema': one_scene_rewrite_schema_for(scene.scene_id)}}))
        context_check(url, prompts, 4096, 12288)
        manifest = run_ng(config)
        print(f'Stage A finished: {manifest['tasks_completed']}/48 complete base intervals. Stop Gemma in Terminal 1; start server-qwen before Stage C.')
    elif action == 'stage-c':
        from storygen_feature.rewritten import extract_rewritten_feature_set
        from storygen_measurement_core import MeasurementProtocol, CanonicalFeatureScorer
        from storygen_measurement_core.preflight import validate_runtime_identity
        from storygen_measurement_core.client import build_request_payload
        rw = read(Path(config['rewrite_output']) / 'rewrite_run_manifest.json')
        if rw['prompt_contract_id'] != 'NG-v0' or rw['tasks_completed'] + rw['tasks_failed'] != 48:
            raise RuntimeError('Stage A is incomplete; preserve artifacts and STOP')
        url = live_runtime(config, 'qwen')
        workspace = Path(config['workspace'])
        core = workspace / 'storygen-feature-extraction/measurement'
        protocol = MeasurementProtocol.load(core, 'configs/feature_measurement_v1.yaml')
        validate_runtime_identity(protocol, model_file=config['models']['qwen']['path'], server_manifest=config['qwen_manifest'], require_slots=8, require_live_server=True)
        scorer = CanonicalFeatureScorer(protocol, use_cache=False)
        prompts = []
        for task in config['base_tasks']:
            file = Path(config['rewrite_output']) / 'tasks' / task['task_id'] / 'rewritten_scenes.json'
            if file.is_file():
                prompts += [build_request_payload(prompt=scorer._render(task['source_film_id'], s['scene_id'], s['title'], s['content']), model=protocol.model['alias'], schema=protocol.schema, decoding=protocol.decoding, system_instruction=protocol.system_instruction, response_schema_name=protocol.response_schema_name) for s in read(file)['rewritten_scenes']]
        context_check(url, prompts, 256, 12288)
        try:
            extract_rewritten_feature_set(project_root=workspace / 'storygen-feature-extraction', core_root=core, protocol_path=Path('configs/feature_measurement_v1.yaml'), rewrite_run=Path(config['rewrite_output']), reference_feature_set_manifest=Path(config['reference']['path']), taskset_runtime=Path(config['base_runtime']), feature_set_id='ng_v0_fev1_4', output_root=Path(config['measurement_output']).parent, model_file=Path(config['models']['qwen']['path']), server_manifest=Path(config['qwen_manifest']), concurrency=8, progress_mode='always')
        except RuntimeError:
            if not (Path(config['measurement_output']) / 'feature_set_manifest.json').is_file():
                raise
            print('Stage C recorded failed base intervals; all 240 attempts remain in Stage D denominators.')
        print('Stage C finished; Stage D is offline.')
    elif action == 'stage-d':
        from storygen_evaluation.ng_baseline import evaluate_ng
        print(evaluate_ng(config))
