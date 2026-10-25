"""E04 offline preparation and explicit author-run stages; no implicit inference."""
from .technical import Tee, checked, context_check, fingerprints, live_runtime, read, require_stage, sealed_stage, server_command, sha, verified_live, verify_files, verify_port_owner, write
from .bindings import REWRITE, imports, git
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
from pathlib import Path
import argparse, io, json, os, shutil, sys, tempfile
from .bindings import REWRITE, imports
from .technical import read, write, sha, git, server_command, context_check
from .technical import fingerprints, verify_files, verified_live, sealed_stage, require_stage, Tee
from .repetition_api import load_config as frozen_config
CONDITIONS = ('MP-DIR-v1', 'MP-NUM-v1')
ACTIONS = ('preflight', 'server-gemma', 'generate-dir', 'generate-num', 'validate-generation', 'server-qwen', 'reanalyze', 'evaluate', 'status')
MUTABLE_OPERATIONAL_FILES = ('storygen-rewrite-depot/runs/reviewer_round1/E03_DP48_extension/20261011T072158702179Z/logs/SERVER_QWEN.log',)

def protection_scope(protected, workspace):
    """Classify exactly the reviewed telemetry path; keep diagnostic identities."""
    allowed = {str(Path(workspace) / p) for p in MUTABLE_OPERATIONAL_FILES}
    immutable = {p: h for p, h in protected.items() if p not in allowed}
    telemetry = {p: dict(classification='mutable_operational_telemetry', reason='Reviewed llama.cpp server log; not a scientific input/output or sealed receipt', frozen_sha256=h, observed_sha256=sha(p) if Path(p).is_file() else None) for p, h in protected.items() if p in allowed}
    return (immutable, telemetry)

def verify_scientific_dependencies(protected, workspace):
    immutable, telemetry = protection_scope(protected, workspace)
    verify_files(immutable)
    return (immutable, telemetry)

def load_config(run):
    if read(run / 'CONFIG.json').get('contract') != 'storygen.E04/1.0':
        raise RuntimeError('Only an isolated E04 root is accepted')
    return frozen_config(run)

def capture_pairs(config):
    """Actual canonical scheduler/engine/HTTP transport; stub responses in temp only."""
    import httpx
    from storygen.rewrite_v1_3 import runner
    from storygen.rewrite_v1_3.matched_prompt import runner_bindings, request_seed, compare_pair
    captured = {}
    primary = read(config['primary_requests'])
    seeds = {request_seed(p['task_id'], p['scene_id'], 1): (p['task_id'], p['scene_id']) for p in primary}
    with tempfile.TemporaryDirectory(prefix='E04_offline_transport_') as tmp:
        for condition in CONDITIONS:

            def handle(request):
                payload = json.loads(request.content)
                tid, sid = seeds[payload['seed']]
                captured[condition, tid, sid] = payload
                user = json.loads(payload['messages'][1]['content'])
                scene = user['source_scene']
                response = json.dumps(dict(scene_id=sid, title=scene['title'], content=scene['content'], change_summary='Offline identity fixture only'))
                return httpx.Response(200, json={'choices': [{'message': {'content': response}}]})
            from storygen.services.vllm_client import VLLMClient
            factory = lambda **kw: VLLMClient(**kw, transport=httpx.MockTransport(handle))
            output = Path(tmp) / condition
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), runner_bindings(runner=runner, config=config, condition=condition, output=output, client_factory=factory) as abort:
                runner.run_taskset(project_root=REWRITE, taskset_path=Path(config['tasksets'][condition]), feature_set_manifest=Path(config['reference']['path']), output_root=output.parent, run_id=output.name, model=config['gemma_server']['model_alias'], model_file=Path(config['models']['gemma']['path']), quantization=config['gemma_server']['quantization'], server_manifest=Path(config['gemma_manifest']), strategy=condition, base_url='http://offline.invalid/v1', temperature=0.2, schema_retry_count=1, max_tokens=4096, concurrency=4, timeout=900)
                if abort.is_set():
                    raise RuntimeError('Offline prompt provenance invariant failed')
    if len(captured) != 1600:
        raise RuntimeError('Actual canonical transport did not capture exactly 1600 primary requests')
    pairs = []
    for p in primary:
        if p['condition'] != CONDITIONS[0]:
            continue
        tid, sid = (p['task_id'], p['scene_id'])
        a = captured[CONDITIONS[0], tid, sid]
        b = captured[CONDITIONS[1], tid, sid]
        pairs.append(dict(task_id=tid, scene_id=sid, **compare_pair(a, b)))
    return dict(status='PASS', capture='actual canonical run_taskset + engine + VLLMClient with httpx.MockTransport; temporary output roots removed', pairs=pairs, unexpected_model_facing_differences=0, actual_primary_requests=1600, common_repair='unchanged repair_per_scene_prompt_v1.json; original user request carries only allowed numeric manipulation; invalid responses/error diagnostics may differ')

def prepare(original, before_path):
    old = read(original / 'CONFIG.json')
    w = Path(old['workspace'])
    imports(w)
    from storygen.rewrite_v1_3.matched_prompt import select_tasks, SELECTION_SEED, request_seed, render, system, prompt_provenance, ALLOWED_PATHS
    from storygen.rewrite_v1_3.repeatability import payload_for
    from storygen.rewrite_v1_3.provenance import sha256_json
    from storygen_evaluation.provenance import validate_reference, validate_runtime, validate_curves, ArtifactResolver, structure_sha
    from storygen.services.rewrite_engine import load_selected_scenes
    from storygen.schemas.transfer import TransferPlan
    before = read(before_path)
    _, telemetry = verify_scientific_dependencies(before['protected'], w)
    if sha(original / 'CONFIG.json') != (original / 'CONFIG.sha256').read_text().strip():
        raise RuntimeError('Historical E03 configuration seal mismatch')
    parent = read(original / 'inputs/PARENT_RUNTIME_240.json')
    reference = read(old['reference']['path'])
    validate_reference(reference)
    expected = 'sha256:840aafe93408d41f3ef2e8fe791b0401ce52008060031a58aa46e4e28944bcdb'
    if structure_sha(parent['tasks']) != expected or len(parent['tasks']) != 240:
        raise RuntimeError('Original Qwen TasksetV5 mismatch')
    validate_runtime(parent, reference, Path(old['reference']['path']), ArtifactResolver())
    for key, ref in old['models'].items():
        if sha(ref['path']) != ref['sha256']:
            raise RuntimeError('Historical checkpoint mismatch: ' + key)
    chosen = select_tasks(parent['tasks'])
    ids = [t['task_id'] for t in chosen]
    tasks = [t for t in parent['tasks'] if t['task_id'] in ids]
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    roots = {k: w / (repo + '-depot') / 'runs/reviewer_round1/E04_matched_prompt' / stamp for k, repo in [('rewrite', 'storygen-rewrite'), ('feature', 'storygen-feature-extraction'), ('evaluation', 'storygen-evaluation')]}
    for root in roots.values():
        root.mkdir(parents=True, exist_ok=False)
    run = roots['rewrite']
    write(run / 'manifests/BEFORE_CHANGES.json', before)
    write(run / 'manifests/PROTECTION_POLICY.json', dict(version='E04.protection-scope.v1', immutable_policy='Strict SHA256 for every scientific/unknown protected file; only the exact reviewed path is telemetry', mutable_operational_files=telemetry, predecessor_run=before.get('preflight_fix_from')))
    projection = {**parent, 'tasks': tasks, 'structure_sha256': structure_sha(tasks), 'e04_projection': 'execution-only, frozen original targets'}
    write(run / 'inputs/PARENT_RUNTIME_240.json', parent)
    write(run / 'inputs/SELECTED_TASKSET.json', projection)
    from collections import Counter
    selection = dict(seed=SELECTION_SEED, rng='NumPy PCG64/default_rng', method='Shuffle sorted base IDs and sorted feature names with seed4204. For base i select axes (2i)%5 and (2i+1)%5 from cyclic feature list. Sort chosen tasks by ID.', metadata_fields=['task_id', 'base_interval_id', 'selected_features', 'source_film_id', 'interval_type', 'source_scene_ids'], performance_blind=True, parent_structure_sha256=expected, selected_task_ids=ids, base_interval_ids=sorted({t['base_interval_id'] for t in tasks}), features=dict(Counter((t['selected_features'][0] for t in tasks))), lengths=dict(Counter((t['interval_type'] for t in tasks))), films=dict(Counter((t['source_film_id'] for t in tasks))), tasks=[dict(task_id=t['task_id'], base_interval_id=t['base_interval_id'], feature=t['selected_features'][0], interval_type=t['interval_type'], source_film_id=t['source_film_id']) for t in tasks], conditions={c: dict(task_ids=ids, projection_structure_sha256=structure_sha(tasks)) for c in CONDITIONS})
    write(run / 'manifests/TASK_SELECTION.json', selection)
    tasksets = {c: str(run / 'inputs/SELECTED_TASKSET.json') for c in CONDITIONS}
    frozen = run / 'inputs/frozen_plans'
    controls = read(original / 'P01.json')['controls']
    requests = []
    inputs = {}
    for task in tasks:
        tid = task['task_id']
        plans = []
        for control in controls:
            source = Path(control['rewrite_manifest']['path']).parent / 'tasks' / tid / 'transfer_plan.json'
            plan = read(source)
            inputs[str(source)] = sha(source)
            plan['feature_source_path'] = task['source_feature_path']
            plan['reference_feature_source_path'] = task['reference_feature_path']
            plans.append(plan)
        if plans[0] != plans[1]:
            raise RuntimeError('Historical DP/CG frozen targets differ: ' + tid)
        write(frozen / 'tasks' / tid / 'transfer_plan.json', plans[0])
        plan = TransferPlan.model_validate(plans[0])
        scenes = load_selected_scenes(task['source_script_path'], task['source_scene_ids'])
        if [d.scene_id for d in plan.per_scene_target_values] != task['source_scene_ids']:
            raise RuntimeError('Frozen directive source scene order mismatch')
        for path in (task['source_script_path'], task['source_feature_path'], task['reference_feature_path']):
            inputs[path] = sha(path)
        for condition in CONDITIONS:
            for i, (scene, directive) in enumerate(zip(scenes, plan.per_scene_target_values, strict=True)):
                user = render(condition, scene=scene, directive=directive, plan=plan, scene_position_index=i, scene_count=len(scenes), max_scene_chars=12000)
                from storygen.services.per_scene_rewrite_engine import one_scene_rewrite_schema_for
                payload = payload_for(user, old['gemma_server']['model_alias'], system=system(), format_schema=one_scene_rewrite_schema_for(scene.scene_id), options={'temperature': 0.2, 'max_tokens': 4096})
                requests.append(dict(condition=condition, task_id=tid, base_interval_id=task['base_interval_id'], scene_id=scene.scene_id, feature=task['selected_features'][0], source_scene_hash=sha256_json(json.loads(user)['source_scene']), target_plan_hash=sha(frozen / 'tasks' / tid / 'transfer_plan.json'), source_characters=len(scene.content), historical_12000_character_cap_applied=len(scene.content) > 12000, prompt_hash=sha256_json(payload['messages']), request_contract_hash=sha256_json(payload), payload=payload))
    validate_curves(tasks, frozen, frozen, Path(old['reference']['path']), reference, ArtifactResolver())
    if len(requests) != 1600:
        raise RuntimeError('E04 exact primary scope mismatch')
    seedrows = [dict(task_id=p['task_id'], scene_id=p['scene_id'], primary_seed=request_seed(p['task_id'], p['scene_id'], 1), repair_seed=request_seed(p['task_id'], p['scene_id'], 2)) for p in requests if p['condition'] == CONDITIONS[0]]
    if len({r[k] for r in seedrows for k in ('primary_seed', 'repair_seed')}) != 1600:
        raise RuntimeError('Unrelated E04 request seed collision')
    write(run / 'inputs/PRIMARY_REQUESTS.json', requests)
    for key in ('gemma', 'qwen'):
        write(run / f'manifests/{key.upper()}_SERVER.json', old[key + '_server'])
    seed_support = read(original / 'manifests/SEED_SUPPORT.json')
    verify_files(seed_support['evidence'])
    write(run / 'manifests/SEED_PROTOCOL.json', dict(protocol='E04.seed.v1', algorithm='1 + int_big_endian(first8(SHA256(E04.seed.v1|task_id|scene_id|attempt))) modulo 2147483646', intentional_pair_equality=True, condition_excluded=True, distinct_unrelated_seeds=1600, requests=seedrows, backend_support=seed_support, limitation='Paired seeds control variance; they do not eliminate stochastic differences or guarantee identical decoding paths.'))
    write(run / 'manifests/INPUT_MANIFEST.json', dict(parent=old['frozen_taskset'], migrated_parent=dict(path=str(original / 'inputs/PARENT_RUNTIME_240.json'), sha256=sha(original / 'inputs/PARENT_RUNTIME_240.json')), reference=old['reference'], input_hashes=inputs, historical_prompts={str(p): h for p, h in before['protected'].items() if '/rewrite/prompts/' in p}, frozen_plans='Historical plans copied with explicit depot path relocation only; no target construction'))
    c = {k: old[k] for k in ('workspace', 'reference', 'frozen_taskset', 'models', 'measurement', 'decoding', 'gemma_server', 'qwen_server', 'binary_sha256')}
    c.update(contract='storygen.E04/1.0', experiment_id=stamp, roots={k: str(p) for k, p in roots.items()}, selection=selection, tasksets=tasksets, primary_requests=str(run / 'inputs/PRIMARY_REQUESTS.json'), frozen_plans=str(frozen), gemma_manifest=str(run / 'manifests/GEMMA_SERVER.json'), qwen_manifest=str(run / 'manifests/QWEN_SERVER.json'), prompt_provenance=prompt_provenance(), allowed_numeric_diff_paths=ALLOWED_PATHS, executions={c: [dict(repetition_id=1, generation=str(run / 'generation' / c), reanalysis=str(roots['feature'] / 'reanalysis' / f'e04_{stamp}_{c}_fev1_4'))] for c in CONDITIONS}, evaluation_output=str(roots['evaluation'] / 'evaluation/T04'))
    print('E04 preparation: capturing all 1600 actual transport requests using offline stubs; no real inference', flush=True)
    write(run / 'manifests/PROMPT_MATCHING.json', capture_pairs(c))
    write(run / 'manifests/MODEL_PROVENANCE.json', {k: c[k] for k in ('models', 'gemma_server', 'qwen_server', 'measurement', 'decoding', 'binary_sha256')})
    write(run / 'P01.json', dict(status='PASS', config_draft=c, scientific_results='NOT_RUN'))
    print('P01 PASS: ' + str(run))
    return run

def preflight(run):
    c = load_config(run)
    from storygen.rewrite_v1_3.matched_prompt import select_tasks, compare_pair, request_seed, prompt_provenance
    from storygen_evaluation.provenance import validate_reference, validate_runtime, validate_curves, ArtifactResolver, structure_sha
    from storygen_measurement_core import MeasurementProtocol
    from storygen_measurement_core.preflight import validate_runtime_identity
    parent = read(run / 'inputs/PARENT_RUNTIME_240.json')
    tasks = read(c['tasksets'][CONDITIONS[0]])['tasks']
    if structure_sha(parent['tasks']) != c['selection']['parent_structure_sha256'] or [t['task_id'] for t in select_tasks(parent['tasks'])] != [t['task_id'] for t in tasks] or len(tasks) != 96:
        raise RuntimeError('E04 frozen selection cannot be reproduced')
    ref = read(c['reference']['path'])
    validate_reference(ref)
    validate_runtime(read(c['tasksets'][CONDITIONS[0]]), ref, Path(c['reference']['path']), ArtifactResolver())
    validate_curves(tasks, Path(c['frozen_plans']), Path(c['frozen_plans']), Path(c['reference']['path']), ref, ArtifactResolver())
    pp = read(c['primary_requests'])
    pairs = {(p['condition'], p['task_id'], p['scene_id']): p for p in pp}
    if len(pairs) != 1600:
        raise RuntimeError('E04 primary prompt count mismatch')
    for p in pp:
        if p['condition'] == CONDITIONS[0]:
            compare_pair(p['payload'], pairs[CONDITIONS[1], p['task_id'], p['scene_id']]['payload'])
    if prompt_provenance() != c['prompt_provenance']:
        raise RuntimeError('E04 shared prompt assets changed')
    proto = MeasurementProtocol.load(Path(c['workspace']) / 'storygen-feature-extraction/measurement', 'configs/feature_measurement_v1.yaml')
    if proto.manifest() != c['measurement'] or ref['measurement'] != c['measurement']:
        raise RuntimeError('Original Qwen protocol changed')
    validate_runtime_identity(proto, model_file=c['models']['qwen']['path'], server_manifest=c['qwen_manifest'], require_slots=8)
    print('P01/P02/P03 E04 offline preflight PASS; scientific results NOT_RUN', flush=True)
    return c

def generation(c, condition):
    from storygen.rewrite_v1_3 import runner
    from storygen.rewrite_v1_3.matched_prompt import runner_bindings
    print(f'E04 | {condition} | PREPARING live runtime / complete prompt capacity checks', flush=True)
    url = verified_live(c, 'gemma')
    context_check(url, [p['payload'] for p in read(c['primary_requests']) if p['condition'] == condition], 4096, 12288)
    output = Path(c['executions'][condition][0]['generation'])
    if output.exists():
        raise FileExistsError('E04 does not resume/overwrite')
    with runner_bindings(runner=runner, config=c, condition=condition, output=output) as abort:
        try:
            runner.run_taskset(project_root=REWRITE, taskset_path=Path(c['tasksets'][condition]), feature_set_manifest=Path(c['reference']['path']), output_root=output.parent, run_id=output.name, model=c['gemma_server']['model_alias'], model_file=Path(c['models']['gemma']['path']), quantization=c['gemma_server']['quantization'], server_manifest=Path(c['gemma_manifest']), strategy=condition, base_url=c['gemma_server']['base_url'], temperature=0.2, schema_retry_count=1, max_tokens=4096, concurrency=4, timeout=900)
        except RuntimeError as exc:
            m = output / 'rewrite_run_manifest.json'
            if not m.is_file() or str(exc) != f'{read(m)['tasks_failed']} rewrite tasks failed; artifacts preserved':
                raise
            print('Canonical generation failures retained: ' + str(exc), flush=True)
        if abort.is_set():
            raise RuntimeError('E04 essential provenance invariant failed')
    print(f'E04 {condition} GENERATION stage COMPLETE; failures retained', flush=True)
    return [output]

def validate_generation(c):
    from storygen.rewrite_v1_3.matched_prompt import request_seed, prompt_provenance
    from storygen.rewrite_v1_3.provenance import sha256_json
    from storygen.rewrite_v1_3.repeatability import payload_for
    from storygen_evaluation.provenance import validate_curves, ArtifactResolver
    expected = {(p['condition'], p['task_id'], p['scene_id']): p for p in read(c['primary_requests'])}
    results = []
    for condition in CONDITIONS:
        output = Path(c['executions'][condition][0]['generation'])
        tasks = read(c['tasksets'][condition])['tasks']
        m = read(output / 'rewrite_run_manifest.json')
        if m['prompt_contract_id'] != condition or m['prompt_provenance'] != prompt_provenance() or m['decoding'] != c['decoding'] or (m['model']['file_sha256'] != c['models']['gemma']['sha256']) or (m['tasks_completed'] + m['tasks_failed'] != 96):
            raise RuntimeError('E04 generation manifest identity mismatch')
        rows = [json.loads(line) for line in (output / 'E04_REQUESTS.jsonl').read_text().splitlines()]
        started = [r for r in rows if r['completion_status'] == 'REQUEST_STARTED']
        seen = set()
        for r in started:
            key = (r['task_id'], r['scene_id'], r['attempt'])
            p = expected[condition, key[0], key[1]]
            if key in seen or r['condition'] != condition or r['sampling_seed'] != request_seed(*key) or (r['attempt'] not in (1, 2)) or (r['source_scene_hash'] != p['source_scene_hash']) or (r['target_plan_hash'] != p['target_plan_hash']):
                raise RuntimeError('E04 request audit seed/source/target identity mismatch')
            seen.add(key)
            if r['attempt'] == 1 and (r['prompt_hash'] != p['prompt_hash'] or r['request_sha256'] != sha256_json({**p['payload'], 'seed': request_seed(*key)})):
                raise RuntimeError('E04 primary request audit changed')
        validate_curves(tasks, output, output, Path(c['reference']['path']), read(c['reference']['path']), ArtifactResolver())
        executions = []
        for t in tasks:
            td = output / 'tasks' / t['task_id']
            phase = td / 'phase_status.json'
            good = phase.is_file() and read(phase).get('rewrite_completed') is True
            if read(td / 'transfer_plan.json') != read(Path(c['frozen_plans']) / 'tasks' / t['task_id'] / 'transfer_plan.json'):
                raise RuntimeError('E04 executed target plan changed')
            if good:
                scenes = read(td / 'rewritten_scenes.json')['rewritten_scenes']
                if [s['scene_id'] for s in scenes] != t['source_scene_ids'] or any(((t['task_id'], sid, 1) not in seen for sid in t['source_scene_ids'])):
                    raise RuntimeError('E04 successful output lacks fresh exact scene evidence')
            elif not (td / 'rewrite_failure.json').is_file():
                raise RuntimeError('E04 generation failure lacks evidence')
            for path in td.glob('per_scene/*/rewrite_request.json'):
                r = read(path)
                p = expected[condition, t['task_id'], r['expected_scene_id']]
                actual = payload_for(r['user_instruction'], r['model'], system=r['system_instruction'], format_schema=r['format_schema'], format_json=r['format_json'], options={'temperature': r['temperature'], 'max_tokens': r['rewrite_max_tokens']})
                if sha256_json(actual) != p['request_contract_hash']:
                    raise RuntimeError('Saved E04 model-facing request changed')
            for sid in t['source_scene_ids']:
                p = expected[condition, t['task_id'], sid]
                scene = next((s for s in scenes if s['scene_id'] == sid), None) if good else None
                executions.append(dict(experiment_id=c['experiment_id'], condition=condition, task_id=t['task_id'], base_interval_id=t['base_interval_id'], feature=t['selected_features'][0], scene_id=sid, source_scene_hash=p['source_scene_hash'], target_plan_hash=p['target_plan_hash'], prompt_hash=p['prompt_hash'], sampling_seed=request_seed(t['task_id'], sid, 1), model_checkpoint_sha256=c['models']['gemma']['sha256'], generation_settings=c['decoding'], output_path=str(td / 'rewritten_scenes.json'), output_hash=sha256_json(scene) if scene else None, completion_status='SUCCESS' if good else 'GENERATION_FAILED', failure_reason=None if good else read(td / 'rewrite_failure.json')))
        results.extend(executions)
    return results

def reanalysis(c):
    from storygen_feature.rewritten import extract_rewritten_feature_set
    from storygen_measurement_core import MeasurementProtocol, CanonicalFeatureScorer
    from storygen_measurement_core.client import build_request_payload
    from storygen_measurement_core.preflight import validate_runtime_identity
    feature = Path(c['workspace']) / 'storygen-feature-extraction'
    core = feature / 'measurement'
    print('E04 REANALYSIS PREPARING live Qwen runtime and complete prompt checks', flush=True)
    url = verified_live(c, 'qwen')
    protocol = MeasurementProtocol.load(core, 'configs/feature_measurement_v1.yaml')
    validate_runtime_identity(protocol, model_file=c['models']['qwen']['path'], server_manifest=c['qwen_manifest'], require_slots=8, require_live_server=True)
    scorer = CanonicalFeatureScorer(protocol, use_cache=False)
    outputs = []
    for condition in CONDITIONS:
        execution = c['executions'][condition][0]
        rewrite = Path(execution['generation'])
        output = Path(execution['reanalysis'])
        prompts = []
        if output.exists():
            raise FileExistsError('E04 reanalysis does not resume/overwrite')
        for t in read(c['tasksets'][condition])['tasks']:
            td = rewrite / 'tasks' / t['task_id']
            if (td / 'phase_status.json').is_file() and read(td / 'phase_status.json').get('rewrite_completed') is True:
                for scene in read(td / 'rewritten_scenes.json')['rewritten_scenes']:
                    prompts.append(build_request_payload(prompt=scorer._render(t['source_film_id'], scene['scene_id'], scene['title'], scene['content']), model=protocol.model['alias'], schema=protocol.schema, decoding=protocol.decoding, system_instruction=protocol.system_instruction, response_schema_name=protocol.response_schema_name))
        print(f'E04 | {condition} | REANALYSIS preparing {len(prompts)}/800 eligible positions; complete-task failures excluded visibly', flush=True)
        context_check(url, prompts, 256, 12288)
        try:
            extract_rewritten_feature_set(project_root=feature, core_root=core, protocol_path=Path('configs/feature_measurement_v1.yaml'), rewrite_run=rewrite, reference_feature_set_manifest=Path(c['reference']['path']), taskset_runtime=Path(c['tasksets'][condition]), feature_set_id=output.name, output_root=output.parent, model_file=Path(c['models']['qwen']['path']), server_manifest=Path(c['qwen_manifest']), concurrency=8, progress_mode='always')
        except RuntimeError as exc:
            m = output / 'feature_set_manifest.json'
            if not m.is_file() or str(exc) != f'{read(m)['tasks_failed']} rewritten Feature Extraction tasks failed; valid artifacts were preserved':
                raise
            print('Canonical reanalysis failures retained: ' + str(exc), flush=True)
        outputs.append(output)
        print(f'E04 {condition} REANALYSIS complete; conditions {len(outputs)}/2', flush=True)
    return outputs

def status(run):
    c = read(run / 'CONFIG.json')
    if c.get('contract') != 'storygen.E04/1.0':
        raise RuntimeError('E04 root required')
    stages = {p.stem: read(p) for p in (run / 'runtime').glob('STAGE_*.json')}
    jobs = {}
    for condition in CONDITIONS:
        executions = c.get('executions', {}).get(condition, [])
        summaries = [read(p) for e in executions for p in Path(e['generation']).glob('tasks/*/per_scene/*/scene_summary.json')]
        jobs[condition] = dict(completed=len(summaries), total=800, succeeded=sum((s.get('succeeded') is True for s in summaries)), failed=sum((s.get('succeeded') is not True for s in summaries)))
    logs = {p.name: p.read_text()[-2500:] for p in (run / 'logs').glob('*.log')}
    import re
    times = [(p.name, re.findall('elapsed=([0-9:]+)\\s+eta=([0-9:-]+)', p.read_text())) for p in (run / 'logs').glob('*.log')]
    print(json.dumps(dict(experiment_id=c['experiment_id'], preparation=read(run / 'VALIDATION_RECEIPT.json'), stages=stages, jobs=jobs, last_known_progress=[dict(log=name, elapsed=v[-1][0], ETA=v[-1][1]) for name, v in times if v], output_paths=c['roots'], progress_logs=logs, note='Elapsed/ETA unavailable before observed progress. Completed counters are final canonical scene summaries; started HTTP requests do not count as completed.'), indent=2))

def execute(action, run):
    if action == 'status':
        return status(run)
    c = load_config(run)
    if action == 'preflight':
        return preflight(run)
    if action.startswith('server-'):
        key = action.split('-')[1]
        if key == 'qwen':
            require_stage(run, 'VALIDATE_GENERATION')
        record = run / 'runtime' / ('SERVER_' + key.upper() + '.json')
        record.parent.mkdir(exist_ok=True)
        if record.exists():
            raise FileExistsError('Existing author server receipt cannot be replaced')
        command = server_command(c[key + '_server'])
        write(record, dict(pid=os.getpid(), command=command, role=key, server_manifest=c[key + '_manifest']))
        return os.execve(command[0], command, os.environ.copy())
    if action == 'generate-dir':
        return sealed_stage(run, 'GENERATE_DIR', lambda: generation(c, CONDITIONS[0]))
    if action == 'generate-num':
        require_stage(run, 'GENERATE_DIR')
        return sealed_stage(run, 'GENERATE_NUM', lambda: generation(c, CONDITIONS[1]))
    if action == 'validate-generation':
        require_stage(run, 'GENERATE_DIR')
        require_stage(run, 'GENERATE_NUM')

        def validate():
            write(run / 'reports/GENERATION_VALIDATION.json', validate_generation(c))
            return [run / 'reports/GENERATION_VALIDATION.json']
        return sealed_stage(run, 'VALIDATE_GENERATION', validate)
    if action == 'reanalyze':
        require_stage(run, 'VALIDATE_GENERATION')
        return sealed_stage(run, 'REANALYZE', lambda: reanalysis(c))
    if action == 'evaluate':
        require_stage(run, 'GENERATE_DIR')
        require_stage(run, 'GENERATE_NUM')
        require_stage(run, 'VALIDATE_GENERATION')
        require_stage(run, 'REANALYZE')
        from storygen_evaluation.matched_prompt import evaluate
        return sealed_stage(run, 'EVALUATE', lambda: [evaluate(c)])
    raise ValueError(action)

def author_commands(run):
    return '# E04 author commands\n\nIn BOTH terminals:\n```bash\n' + f'RUN={str(run)!r}\ne4() {{ /home/alp-emre/.venv/bin/python3 {REWRITE}/tools/e04_matched_prompt.py "$1" --run "$RUN"; }}\n```\n\nTerminal 2 before server start:\n```bash\ne4 preflight\n```\n\nTerminal 1:\n```bash\ne4 server-gemma\n```\n\nTerminal 2, wait for each to complete:\n```bash\ne4 generate-dir\ne4 generate-num\ne4 validate-generation\n```\n\nKeep Gemma loaded across both conditions. After successful validation, manually Ctrl+C in Terminal 1, then:\n```bash\ne4 server-qwen\n```\n\nTerminal 2:\n```bash\ne4 reanalyze\ne4 evaluate\ne4 status\n```\n\nNo automatic switching, restart, overwrite or resume. Interrupted stages block subsequent work pending explicit recovery review. Preserve receipts and incomplete outputs. Complete context checks run before completions and stop on overflow with frozen settings unchanged. Scientific task failures are retained in all-attempt denominators; G remains unavailable on failures.\n'

def finalize(run, tests_path):
    if (run / 'CONFIG.json').exists():
        raise FileExistsError('E04 already finalized')
    c = read(run / 'P01.json')['config_draft']
    before = read(run / 'manifests/BEFORE_CHANGES.json')
    w = Path(c['workspace'])
    imports(w)
    immutable, telemetry = verify_scientific_dependencies(before['protected'], w)
    tests = read(tests_path)
    if tests['failed'] or tests['skipped'] or tests['passed'] < 1:
        raise RuntimeError('Offline tests must pass without skips')
    c['source_commits'] = {r: git(w / r, 'rev-parse', 'HEAD') for r in before['repositories']}
    if any((git(w / r, 'status', '--porcelain') for r in c['source_commits'])):
        raise RuntimeError('Source worktrees must be clean')
    c['offline_tests'] = tests
    c['protected'] = immutable
    c['mutable_operational_telemetry'] = telemetry
    c['predecessor_run'] = before.get('preflight_fix_from')
    for r in c['source_commits']:
        for name in git(w / r, 'ls-files').splitlines():
            p = w / r / name
            if p.is_file():
                c['protected'][str(p)] = sha(p)
    c['protected'].update(fingerprints([run / 'inputs', run / 'manifests']))
    c['protected'][str(run / 'P01.json')] = sha(run / 'P01.json')
    write(run / 'CONFIG.json', c)
    (run / 'CONFIG.sha256').write_text(sha(run / 'CONFIG.json') + '\n')
    from storygen_evaluation.matched_prompt import prepare_tables
    prepare_tables(Path(c['roots']['evaluation']) / 'prepared_tables')
    preflight(run)
    receipt = dict(E04_PREPARATION_STATUS='IMPLEMENTATION_READY', P01='PASS', P02='PASS', P03='PASS', scientific_results='NOT_RUN', experiment='HUMAN_RUN_PENDING', offline_tests=tests, canonical_pipeline='UNCHANGED', historical_prompts='UNCHANGED', unexpected_model_facing_differences=0, selected_tasks=96, base_intervals=48, primary_requests=1600, Qwen_maximum=1600, repetitions=1)
    write(run / 'VALIDATION_RECEIPT.json', receipt)
    write(run / 'manifests/VALIDATION_RECEIPT.json', receipt)
    commands = author_commands(run)
    (run / 'AUTHOR_COMMANDS.md').write_text(commands)
    spec = 'E04 tests the joint current/target/delta package under one matched system/user/repair contract. MP-DIR has three null fields; MP-NUM uses exact historical plan values. Both use 96 same single-feature tasks: two per each of 48 original bases. One realization per arm. No historical result substitution. Seeds exclude arm identity; no response cache.\n\nPrimary G=dB-dA using unchanged MAE. Primary contrast is actual paired MP-NUM minus MP-DIR G. Negative gains retained. Canonical TI/DA secondary. Conditional arm results and matched-pair arm means reported separately. Failure-zero all-attempt TI/DA use96 denominator. No G imputation. Bootstrap10000 PCG64seed42 base clusters, percentile95linear; tasks equally weighted, two features bundled. Ten-source-film bootstrap exploratory. Feature/length summaries descriptive. CI crossing zero means no reliable advantage demonstrated, not equivalence; negative excluded-zero CI supports harm, positive supports benefit under this protocol only.\n\nLimitations: does not isolate components current/target/delta, does not establish cause of historical DP/CG differences, does not measure human preference or naturalness, does not test extractor independence. Qwen dependence identified in E01 remains. One realization does not estimate within-task sampling variance. Paired seeds are variance control, not identical random paths. Source windows/films may be dependent. Canonical constant/insufficient-cluster CI remains undefined with reason; no invented p-values.\n'
    (run / 'EXPERIMENT_SPEC.md').write_text(spec)
    changed = {r: git(w / r, 'diff', '--name-only', v['head'], 'HEAD').splitlines() for r, v in before['repositories'].items()}
    report = '# E04-MIN preparation\n\nIMPLEMENTATION_READY; P01/P02/P03 PASS. SCIENTIFIC RESULTS NOT_RUN. HUMAN_RUN_PENDING.\n\n' + spec + '\n\n'
    for label, value in [('Selection (all96 IDs/all48bases/distributions)', c['selection']), ('Input/historical prompt identities', read(run / 'manifests/INPUT_MANIFEST.json')), ('Shared prompt hashes', c['prompt_provenance']), ('Prompt pairing', dict(pairs=800, actual_transport_requests=1600, allowed_numeric_diff_paths=c['allowed_numeric_diff_paths'], unexpected_differences=0)), ('Models/runtime', read(run / 'manifests/MODEL_PROVENANCE.json')), ('Seed protocol', {k: v for k, v in read(run / 'manifests/SEED_PROTOCOL.json').items() if k != 'requests'}), ('Offline tests', tests), ('Source changes', changed), ('Exact commits', c['source_commits']), ('All output roots', c['roots']), ('Qwen mapping', c['executions'])]:
        report += '## ' + label + '\n\n```json\n' + json.dumps(value, indent=2) + '\n```\n\n'
    report += '1600 primary Gemma requests (800 per condition), repairs additional; maximum1600 Qwen scene measurements, successful complete tasks only.192 planned task-condition executions,48 distinct bases. Both arms use original12000-character cap with identical rendered source bytes. Shared canonical schema/repair/preservation/normalizer/validator; E04 bindings restore every original DP/CG/NG dependency after calls. Frozen plans are copied from both historical controls with path migration only; target construction is not rerun.\n\nPreservation fingerprints BEFORE_CHANGES/AFTER_PRESERVATION verify old assets byte-identical. Historical source files unchanged; additive files only. Actual stub HTTP payload matching checks all800 scene pairs and decoding/seed/schema; only three numeric values differ. Synthetic outputs existed only in temporary test roots, never in E04 result trees.\n\nProgress uses canonical ProgressReporter and scheduler: completed/total,percentage,HH:MM:SS elapsed/observedETA,succeeded/failed,scene throughput. Live runtime/hash/token-capacity checks explicitly report PREPARING before generation. Existing pooled transport keeps four Gemma slots; eight Qwen slots. Strict executable/process/port/model/alias/checkpoint/context/continuous-batching validation is reused. Persistent Gemma remains across conditions, Qwen across both reanalyses. No model switching or restarting by scripts. Exclusive logs/receipts/output roots; interrupts preserve artifacts and block later stages. Unexpected invariant failure STOP; known scientific failures retained. Status read-only even after interruption.\n\nT04 author output: ' + c['evaluation_output'] + '; NOT_RUN CSV/Markdown tables: ' + str(Path(c['roots']['evaluation']) / 'prepared_tables') + '\n\n' + commands
    (run / 'PREPARATION_REPORT.md').write_text(report)
    for key in ('feature', 'evaluation'):
        write(Path(c['roots'][key]) / 'PREPARATION_LINK.json', dict(config=str(run / 'CONFIG.json'), report=str(run / 'PREPARATION_REPORT.md')))
    print('E04 IMPLEMENTATION_READY: ' + str(run))
