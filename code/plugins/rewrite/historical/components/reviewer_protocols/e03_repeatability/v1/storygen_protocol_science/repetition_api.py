"""E03 preparation and explicit human-run stages. No stage launches another stage.

prepare/finalize/preflight are strictly offline. Inference is possible only through
the explicitly named generate-cg, generate-dp and reanalyze author commands.
"""
from __future__ import annotations
from .technical import Tee, checked, context_check, fingerprints, live_runtime, read, require_stage, sealed_stage, server_command, sha, verified_live, verify_files, verify_port_owner, write
from .bindings import REWRITE, imports, git
import argparse
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from .bindings import REWRITE, imports
from .technical import sha, read, write, git, server_command, live_runtime, context_check

def preserve_before(workspace, plan_path):
    plan = read(plan_path)
    states = {}
    protected = {str(plan_path): sha(plan_path)}
    for repo in ('storygen-rewrite', 'storygen-feature-extraction', 'storygen-evaluation'):
        path = workspace / repo
        states[repo] = dict(head=git(path, 'rev-parse', 'HEAD'), status=git(path, 'status', '--porcelain'))
        if states[repo]['status']:
            raise RuntimeError('Prepare requires clean source worktrees: ' + repo)
        for name in git(path, 'ls-files').splitlines():
            file = path / name
            if file.is_file():
                protected[str(file)] = sha(file)
    for key in ('taskset', 'reference_feature_set', 'artifact_overrides', 'p01a_gate', 'approved_a6_protocol'):
        ref = plan[key]
        if sha(ref['path']) != ref['sha256']:
            raise RuntimeError('Frozen authority SHA mismatch')
        protected[ref['path']] = ref['sha256']
    directories = [Path(plan['reference_feature_set']['path']).parent]
    for c in plan['runs']:
        if c['display_model'] == 'Gemma-3-12B':
            for key in ('rewrite_manifest', 'reanalysis_manifest', 'evaluation_manifest'):
                if sha(c[key]['path']) != c[key]['sha256']:
                    raise RuntimeError('Historical control SHA mismatch')
                directories.append(Path(c[key]['path']).parent)
    protected.update(fingerprints(directories))
    for p in (workspace / 'storygen-feature-extraction-depot/runs/_inputs/films').glob('*/script.json'):
        protected[str(p)] = sha(p)
    receipt = Path('/tmp') / ('storygen_E03_before_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json')
    write(receipt, dict(repositories=states, protected=protected, plan_path=str(plan_path)))
    return receipt

def finalize(run, tests_path):
    """P02/P03 assembly after P01 and validated source commits; still no HTTP."""
    if (run / 'CONFIG.json').exists():
        raise FileExistsError('E03 already finalized')
    p01 = read(run / 'P01.json')
    if p01['P01'] != 'PASS':
        raise RuntimeError('P01 must PASS first')
    workspace = Path(p01['roots']['rewrite']).parents[4]
    imports(workspace)
    from storygen.rewrite_v1_3.repeatability import select_tasks, SEED_SCHEDULE, request_seed, generation_records
    from storygen.rewrite_v1_3.provenance import prompt_provenance, sha256_json
    from storygen_evaluation.provenance import structure_sha
    from storygen_evaluation.repeatability import prepare_tables
    before = read(run / 'manifests/BEFORE_CHANGES.json')
    verify_files(before['protected'])
    tests = read(tests_path)
    if tests.get('failed') != 0 or tests.get('passed', 0) < 1 or tests.get('skipped') != 0:
        raise RuntimeError('E03 offline regression tests must pass without skips')
    selection = read(run / 'manifests/SELECTION.json')
    parent = read(run / 'inputs/PARENT_RUNTIME_240.json')
    chosen, trials = select_tasks(parent['tasks'])
    if trials != selection['matched_trials'] or any(([t['task_id'] for t in chosen[c]] != selection['conditions'][c]['task_ids'] for c in chosen)):
        raise RuntimeError('Frozen performance-blind selection cannot be reproduced')
    roots = {k: Path(v) for k, v in p01['roots'].items()}
    primary = read(run / 'inputs/PRIMARY_REQUESTS.json')
    executions = {}
    tasksets = {}
    for condition in ('CG-v1', 'DP-v1'):
        tasksets[condition] = str(run / f'inputs/{condition}_RUNTIME.json')
        tasks = read(tasksets[condition])['tasks']
        selection['conditions'][condition]['projection_structure_sha256'] = structure_sha(tasks)
        executions[condition] = [dict(repetition_id=rep, generation=str(run / 'generation' / condition / f'repeat_{rep:02d}'), reanalysis=str(roots['feature'] / 'reanalysis' / condition / f'e03_{run.name}_{condition[:2].lower()}_repeat_{rep:02d}_fev1_4')) for rep in range(1, 6)]
    seeds = [dict(condition=p['condition'], repetition_id=rep, task_id=p['task_id'], scene_id=p['scene_id'], primary_seed=request_seed(p['condition'], rep, p['task_id'], p['scene_id'], 1), repair_seed=request_seed(p['condition'], rep, p['task_id'], p['scene_id'], 2)) for p in primary for rep in range(1, 6)]
    if len(seeds) != 2500 or len({s[key] for s in seeds for key in ('primary_seed', 'repair_seed')}) != 5000:
        raise RuntimeError('E03 seed schedule collision or request-count mismatch')
    write(run / 'manifests/REQUEST_SEEDS.json', dict(schedule=SEED_SCHEDULE, algorithm='E03.seed.v1 SHA256 first 8 bytes; 1 + integer mod 2147483646', requests=seeds))
    commits = {repo: git(workspace / repo, 'rev-parse', 'HEAD') for repo in before['repositories']}
    for repo in commits:
        if git(workspace / repo, 'status', '--porcelain'):
            raise RuntimeError('Dirty source worktree: ' + repo)
    config = dict(contract='storygen.E03/1.0', experiment_id=run.name, workspace=str(workspace), roots=p01['roots'], selection=selection, reference=p01['reference'], frozen_taskset=p01['parent'], models=p01['models'], measurement=p01['measurement'], decoding=p01['decoding'], gemma_server=p01['servers']['gemma'], qwen_server=p01['servers']['qwen'], gemma_manifest=str(run / 'manifests/GEMMA_SERVER.json'), qwen_manifest=str(run / 'manifests/QWEN_SERVER.json'), tasksets=tasksets, primary_requests=str(run / 'inputs/PRIMARY_REQUESTS.json'), frozen_plans=str(run / 'inputs/frozen_plans'), executions=executions, evaluation_output=str(roots['evaluation'] / 'evaluation/T03'), source_commits=commits, binary_sha256=p01['binary_sha256'], seed_schedule=SEED_SCHEDULE, prompt_provenance={c: prompt_provenance(REWRITE / 'rewrite', c) for c in executions}, offline_tests=tests)
    ledger = []
    for condition, repeats in executions.items():
        for execution in repeats:
            ledger.extend([{**r, 'completion_status': 'NOT_RUN', 'failure_reason': None} for r in generation_records(config, condition, execution['repetition_id'], Path(execution['generation']))])
    write(run / 'manifests/PLANNED_EXECUTIONS.json', ledger)
    prepare_tables(roots['evaluation'] / 'prepared_tables', {c: selection['conditions'][c]['task_ids'] for c in executions})
    protected = dict(before['protected'])
    for repo in commits:
        for name in git(workspace / repo, 'ls-files').splitlines():
            path = workspace / repo / name
            if path.is_file():
                protected[str(path)] = sha(path)
    protected.update(fingerprints([run / 'inputs', run / 'manifests']))
    protected[str(run / 'P01.json')] = sha(run / 'P01.json')
    protected[config['gemma_server']['server_binary']] = config['binary_sha256']
    for path in read(run / 'manifests/SEED_SUPPORT.json')['evidence']:
        protected[path] = sha(path)
    config['protected'] = protected
    write(run / 'CONFIG.json', config)
    (run / 'CONFIG.sha256').write_text(sha(run / 'CONFIG.json') + '\n')
    for key, root in roots.items():
        if key != 'rewrite':
            write(root / 'PREPARATION_LINK.json', dict(config=str(run / 'CONFIG.json'), report=str(run / 'PREPARATION_REPORT.md')))
    commands = author_commands(run)
    (run / 'AUTHOR_COMMANDS.md').write_text(commands)
    preflight(run)
    report(config, run, before, commands)
    write(run / 'OFFLINE_GATES.json', dict(P01='PASS', P02='PASS', P03='PASS', status='IMPLEMENTATION_READY', experiment='HUMAN_RUN_PENDING', scientific_results='NOT_RUN', tests=tests, protected_files=len(protected), planned_task_executions=300, planned_primary_scene_requests=2500))
    print('E03 IMPLEMENTATION_READY: ' + str(run))

def load_config(run):
    if sha(run / 'CONFIG.json') != (run / 'CONFIG.sha256').read_text().strip():
        raise RuntimeError('E03 configuration seal mismatch')
    config = read(run / 'CONFIG.json')
    workspace = Path(config['workspace'])
    imports(workspace)
    verify_files(config['protected'])
    for repo, commit in config['source_commits'].items():
        if git(workspace / repo, 'rev-parse', 'HEAD') != commit or git(workspace / repo, 'status', '--porcelain'):
            raise RuntimeError('E03 source identity/worktree changed: ' + repo)
    for ref in config['models'].values():
        if sha(ref['path']) != ref['sha256']:
            raise RuntimeError('Checkpoint identity changed')
    if git(workspace / 'llama.cpp', 'rev-parse', 'HEAD') != config['gemma_server']['llama_cpp_commit']:
        raise RuntimeError('Backend source identity changed')
    for path in (run / 'runtime').glob('STAGE_*.json'):
        if read(path)['status'] != 'COMPLETE':
            raise RuntimeError('Interrupted/failed stage preserved; explicit recovery decision required: ' + str(path))
    return config

def preflight(run):
    config = load_config(run)
    from storygen_evaluation.provenance import validate_reference, validate_runtime, validate_curves, ArtifactResolver, structure_sha
    from storygen_measurement_core import MeasurementProtocol
    from storygen.rewrite_v1_3.repeatability import select_tasks
    reference = read(config['reference']['path'])
    validate_reference(reference)
    parent = read(run / 'inputs/PARENT_RUNTIME_240.json')
    if structure_sha(parent['tasks']) != 'sha256:840aafe93408d41f3ef2e8fe791b0401ce52008060031a58aa46e4e28944bcdb':
        raise RuntimeError('Original ordered structure changed')
    chosen, trials = select_tasks(parent['tasks'])
    if trials != config['selection']['matched_trials']:
        raise RuntimeError('Selection seed/method mismatch')
    for condition in config['executions']:
        projection = read(config['tasksets'][condition])
        tasks = projection['tasks']
        if [t['task_id'] for t in tasks] != [t['task_id'] for t in chosen[condition]]:
            raise RuntimeError('Selected task population changed')
        validate_runtime(projection, reference, Path(config['reference']['path']), ArtifactResolver())
        validate_curves(tasks, Path(config['frozen_plans']), Path(config['frozen_plans']), Path(config['reference']['path']), reference, ArtifactResolver())
    protocol = MeasurementProtocol.load(Path(config['workspace']) / 'storygen-feature-extraction/measurement', 'configs/feature_measurement_v1.yaml')
    if protocol.manifest() != config['measurement'] or reference['measurement'] != config['measurement']:
        raise RuntimeError('Full original Qwen protocol changed')
    from storygen_measurement_core.preflight import validate_runtime_identity
    validate_runtime_identity(protocol, model_file=config['models']['qwen']['path'], server_manifest=config['qwen_manifest'], require_slots=8)
    p01 = read(run / 'P01.json')
    for control in p01['controls']:
        manifest = read(control['rewrite_manifest']['path'])
        if manifest['feature_set_manifest']['sha256'] != config['reference']['sha256'] or manifest['feature_set_manifest']['measurement'] != config['measurement'] or manifest['model']['file_sha256'] != config['models']['gemma']['sha256']:
            raise RuntimeError('Historical Gemma/Qwen scientific lineage mismatch')
    print('P01/P02/P03 offline preflight PASS; no inference performed by preflight', flush=True)
    return config

def validate_generation(config):
    """Offline validation binds all selected tasks, actual seeds and primary prompts."""
    from storygen.rewrite_v1_3.provenance import sha256_json
    from storygen.rewrite_v1_3.repeatability import request_seed, payload_for
    from storygen_evaluation.provenance import validate_curves, ArtifactResolver
    from storygen.rewrite_v1_3.runner import _forbid_prompt
    reference = read(config['reference']['path'])
    primary = read(config['primary_requests'])
    expected = {(p['condition'], p['task_id'], p['scene_id']): p for p in primary}
    result = []
    for condition, repeats in config['executions'].items():
        tasks = read(config['tasksets'][condition])['tasks']
        for execution in repeats:
            output = Path(execution['generation'])
            rep = execution['repetition_id']
            manifest = read(output / 'rewrite_run_manifest.json')
            if manifest['taskset']['sha256'] != sha(config['tasksets'][condition]) or manifest['taskset']['task_count'] != len(tasks) or manifest['prompt_contract_id'] != condition or (manifest['decoding'] != config['decoding']) or (manifest['model']['file_sha256'] != config['models']['gemma']['sha256']) or (manifest['prompt_provenance'] != config['prompt_provenance'][condition]) or (manifest['server_manifest']['content'] != config['gemma_server']):
                raise RuntimeError('E03 rewrite manifest identity/configuration mismatch')
            if {p.name for p in (output / 'tasks').iterdir()} != {t['task_id'] for t in tasks}:
                raise RuntimeError('E03 generated task population mismatch')
            audit = [json.loads(line) for line in (output / 'E03_REQUESTS.jsonl').read_text().splitlines()]
            started = [r for r in audit if r['completion_status'] == 'REQUEST_STARTED']
            seen = set()
            for r in started:
                key = (r['task_id'], r['scene_id'], r['attempt'])
                if key in seen:
                    raise RuntimeError('Duplicate generation execution request')
                seen.add(key)
                seed = request_seed(condition, rep, *key)
                if r['sampling_seed'] != seed or r['condition'] != condition or r['repetition_id'] != rep:
                    raise RuntimeError('E03 actual request seed/repetition mismatch')
                task = next((t for t in tasks if t['task_id'] == r['task_id']), None)
                if task is None or r['scene_id'] not in task['source_scene_ids'] or r['base_interval_id'] != task['base_interval_id']:
                    raise RuntimeError('E03 request task/scene/base binding mismatch')
                if r['attempt'] == 1:
                    p = expected[condition, r['task_id'], r['scene_id']]
                    if r['prompt_hash'] != p['prompt_hash'] or r['request_sha256'] != sha256_json({**p['payload'], 'seed': seed}):
                        raise RuntimeError('E03 actual primary request differs from frozen prompt/settings')
            validate_curves(tasks, output, output, Path(config['reference']['path']), reference, ArtifactResolver())
            for task in tasks:
                td = output / 'tasks' / task['task_id']
                _forbid_prompt(td, condition)
                status = td / 'phase_status.json'
                success = status.is_file() and read(status).get('rewrite_completed') is True
                if success:
                    scenes = read(td / 'rewritten_scenes.json')['rewritten_scenes']
                    if [s['scene_id'] for s in scenes] != task['source_scene_ids'] or any((not s['content'].strip() for s in scenes)):
                        raise RuntimeError('E03 final scene order/content mismatch')
                    if any(((task['task_id'], sid, 1) not in seen for sid in task['source_scene_ids'])):
                        raise RuntimeError('Successful generation lacks fresh primary request evidence')
                elif not (td / 'rewrite_failure.json').is_file():
                    raise RuntimeError('Generation task lacks completion or explicit failure evidence')
                for path in td.glob('per_scene/*/rewrite_request.json'):
                    req = read(path)
                    p = expected[condition, task['task_id'], req['expected_scene_id']]
                    actual = payload_for(req['user_instruction'], req['model'], system=req['system_instruction'], format_schema=req['format_schema'], format_json=req['format_json'], options={'temperature': req['temperature'], 'max_tokens': req['rewrite_max_tokens']})
                    if sha256_json(actual) != p['request_contract_hash']:
                        raise RuntimeError('Saved canonical request differs from frozen E03 request')
            result.append(dict(condition=condition, repetition_id=rep, tasks_planned=len(tasks), tasks_completed=manifest['tasks_completed'], tasks_failed=manifest['tasks_failed'], primary_requests=sum((r['attempt'] == 1 for r in started)), repair_requests=sum((r['attempt'] == 2 for r in started)), available_full_task_scene_outputs=sum((len(t['source_scene_ids']) for t in tasks if (output / 'tasks' / t['task_id'] / 'phase_status.json').is_file() and read(output / 'tasks' / t['task_id'] / 'phase_status.json').get('rewrite_completed') is True))))
    return result

def generation(config, condition):
    from storygen.rewrite_v1_3 import runner
    from storygen.rewrite_v1_3.repeatability import runner_bindings, generation_records
    url = verified_live(config, 'gemma')
    requests = [p['payload'] for p in read(config['primary_requests']) if p['condition'] == condition]
    context_check(url, requests, 4096, 12288)
    outputs = []
    for execution in config['executions'][condition]:
        output = Path(execution['generation'])
        rep = execution['repetition_id']
        if output.exists():
            raise FileExistsError('E03 never resumes/overwrites: ' + str(output))
        with runner_bindings(runner=runner, config=config, condition=condition, repetition=rep, output=output) as abort:
            try:
                runner.run_taskset(project_root=REWRITE, taskset_path=Path(config['tasksets'][condition]), feature_set_manifest=Path(config['reference']['path']), output_root=output.parent, run_id=output.name, model=config['gemma_server']['model_alias'], model_file=Path(config['models']['gemma']['path']), quantization=config['gemma_server']['quantization'], server_manifest=Path(config['gemma_manifest']), strategy=condition, base_url=config['gemma_server']['base_url'], temperature=0.2, schema_retry_count=1, max_tokens=4096, concurrency=4, timeout=900)
            except RuntimeError as exc:
                manifest = output / 'rewrite_run_manifest.json'
                if not manifest.is_file() or str(exc) != f'{read(manifest)['tasks_failed']} rewrite tasks failed; artifacts preserved':
                    raise
                print('\nE03 canonical task failures preserved: ' + str(exc), flush=True)
            if abort.is_set():
                raise RuntimeError('E03 essential provenance invariant failed; STOP')
        write(output / 'E03_EXECUTIONS.json', generation_records(config, condition, rep, output))
        outputs.append(output)
        print(f'E03 {condition} overall repeats {rep}/5; planned primary positions {rep * len(requests)}/{5 * len(requests)}; task failures retained', flush=True)
    return outputs

def reanalysis(config):
    from storygen_feature.rewritten import extract_rewritten_feature_set
    from storygen_measurement_core import MeasurementProtocol, CanonicalFeatureScorer
    from storygen_measurement_core.client import build_request_payload
    from storygen_measurement_core.preflight import validate_runtime_identity
    workspace = Path(config['workspace'])
    feature = workspace / 'storygen-feature-extraction'
    core = feature / 'measurement'
    url = verified_live(config, 'qwen')
    protocol = MeasurementProtocol.load(core, 'configs/feature_measurement_v1.yaml')
    validate_runtime_identity(protocol, model_file=config['models']['qwen']['path'], server_manifest=config['qwen_manifest'], require_slots=8, require_live_server=True)
    scorer = CanonicalFeatureScorer(protocol, use_cache=False)
    outputs = []
    for condition, repeats in config['executions'].items():
        tasks = read(config['tasksets'][condition])['tasks']
        for execution in repeats:
            rewrite = Path(execution['generation'])
            output = Path(execution['reanalysis'])
            prompts = []
            if output.exists():
                raise FileExistsError('E03 reanalysis never resumes/overwrites')
            for task in tasks:
                td = rewrite / 'tasks' / task['task_id']
                if (td / 'phase_status.json').is_file() and read(td / 'phase_status.json').get('rewrite_completed') is True:
                    for scene in read(td / 'rewritten_scenes.json')['rewritten_scenes']:
                        prompts.append(build_request_payload(prompt=scorer._render(task['source_film_id'], scene['scene_id'], scene['title'], scene['content']), model=protocol.model['alias'], schema=protocol.schema, decoding=protocol.decoding, system_instruction=protocol.system_instruction, response_schema_name=protocol.response_schema_name))
            context_check(url, prompts, 256, 12288)
            print(f'E03 Qwen {condition} repeat {execution['repetition_id']}: {len(prompts)} available / {sum((len(t['source_scene_ids']) for t in tasks))} planned positions', flush=True)
            try:
                extract_rewritten_feature_set(project_root=feature, core_root=core, protocol_path=Path('configs/feature_measurement_v1.yaml'), rewrite_run=rewrite, reference_feature_set_manifest=Path(config['reference']['path']), taskset_runtime=Path(config['tasksets'][condition]), feature_set_id=output.name, output_root=output.parent, model_file=Path(config['models']['qwen']['path']), server_manifest=Path(config['qwen_manifest']), concurrency=8, progress_mode='always')
            except RuntimeError as exc:
                manifest = output / 'feature_set_manifest.json'
                if not manifest.is_file() or str(exc) != f'{read(manifest)['tasks_failed']} rewritten Feature Extraction tasks failed; valid artifacts were preserved':
                    raise
                print('\nE03 canonical measurement failures retained: ' + str(exc), flush=True)
            outputs.append(output)
            print(f'E03 reanalysis executions complete {len(outputs)}/10; original Qwen measurements unchanged', flush=True)
    return outputs

def author_commands(run):
    command = f'/home/alp-emre/.venv/bin/python3 {REWRITE}/tools/e03_repeatability.py'
    prefix = f'RUN={str(run)!r}\n'
    return '# E03 author commands\n\nPreparation is NOT_RUN. Only the author executes these stages.\n\nTerminal 1: start Gemma once; keep it loaded for all CG and DP repeats.\n```bash\n' + prefix + f'{command} server-gemma --run "$RUN"\n```\n\nTerminal 2: execute in this order.\n```bash\n' + prefix + '\n'.join((f'{command} {stage} --run "$RUN"' for stage in ('preflight', 'generate-cg', 'generate-dp', 'validate-generation'))) + '\n```\n\nAfter validation, the author presses Ctrl+C in Terminal 1 and switches to Qwen.\n```bash\n' + f'{command} server-qwen --run "$RUN"\n```\n\nTerminal 2:\n```bash\n' + f'{command} reanalyze --run "$RUN"\n{command} evaluate --run "$RUN"\n```\n\nNo automatic restart/resume or overwrite. Any incomplete STAGE receipt blocks later execution. Preserve artifacts and obtain an explicit author recovery decision before any further execution. This wrapper supplies no recovery bypass. Fresh run preparation after review is supported with prepare --plan PATH. Server launch refuses existing server receipts; the author controls stopping/switching. Complete primary prompts and available rewrite measurement prompts are tokenized by the live server before inference; context overflow stops with the frozen settings unchanged. Repair context overflow follows canonical failure handling.\n'

def report(config, run, before, commands):
    changed = {repo: git(Path(config['workspace']) / repo, 'diff', '--name-only', state['head'], config['source_commits'][repo]).splitlines() for repo, state in before['repositories'].items()}
    text = '# E03 generation repeatability preparation\n\nIMPLEMENTATION_READY; P01/P02/P03 PASS. HUMAN_RUN_PENDING. Scientific results NOT_RUN.\n\n'
    text += 'Objective: five fresh Gemma generations of 48 CG-v1 tasks; matched 12-task DP-v1 comparison reuses the CG outputs. This is generation repeatability, not extractor repeatability.\n\n'
    text += 'Original Qwen-bound TasksetV5: 240 tasks, 48 base intervals, five features. Ordered structure SHA256 ' + config['selection']['parent_structure_sha256'] + '. Parent files remain unchanged; execution projections are explicit subsets with exact original IDs and reference bindings.\n\n'
    text += 'Selection seed 4203, NumPy PCG64. ' + config['selection']['method'] + ' No historical TI/DA, quality, or success fields are inspected by selection. All 10 source films occur in both selections.\n\n'
    for c, s in config['selection']['conditions'].items():
        text += f'## {c}\n\nTasks: ' + ', '.join(s['task_ids']) + '\n\nFeatures: ' + json.dumps(s['features']) + '\n\nLengths: ' + json.dumps(s['lengths']) + '\n\nFilms: ' + json.dumps(s['source_films']) + '\n\n'
    text += '## Frozen protocol and provenance\n\nHistorical DP/CG user, system, repair and method assets match historical hashes. All previously tracked source files remain byte-identical; only new E03 files are added. Frozen original transfer plans match both historical controls and the canonical planner exactly after explicit path migration; numbers, directives, alignments and targets are unchanged. All 500 primary requests are rendered and hashed before inference.\n\n'
    text += 'Prompt provenance:\n```json\n' + json.dumps(config['prompt_provenance'], indent=2) + '\n```\n\n'
    text += 'Checkpoints (actual files verified):\n```json\n' + json.dumps(config['models'], indent=2) + '\n```\n\n'
    text += 'Exact historical server profiles and generation settings:\n```json\n' + json.dumps({k: config[k] for k in ('gemma_server', 'qwen_server', 'decoding')}, indent=2) + '\n```\n\n'
    text += 'RNG: canonical client already translates seed into OpenAI JSON; pinned backend server-schema maps it to sampling.seed (see SEED_SUPPORT.json). Master schedules: ' + json.dumps(config['seed_schedule']) + '. For every task/scene/primary-or-repair, SHA256 of `E03.seed.v1|master|condition|task_id|scene_id|attempt` supplies the first eight bytes as big-endian integer; request seed is 1 + value modulo 2147483646. All 2500 primary seeds are distinct. Actual request seeds and prompt/request hashes are flushed to each repeat E03_REQUESTS.jsonl. Seeds are applied only to backend request options, never to prompt text. New independent output roots; no generation caching or historical response reuse. Same persistent model, canonical pooled client/concurrency, task executor and bounded repair policy.\n\n'
    text += 'Planned counts: CG 48×5=240 executions / 400×5=2000 primary requests; DP 12×5=60 / 100×5=500. Total 300 executions of 48 distinct tasks and 2500 primary calls (repairs additional). Qwen reanalysis plans the same 2500 positions; only full canonical successful task outputs can be measured. Scene-level successes inside a failed task remain preserved but are unavailable to canonical full-task reanalysis. Availability, attempted measurements, failures and all planned denominators are reported separately.\n\n'
    text += 'Integration: unchanged canonical run_taskset (temporary E03 dependency bindings supply seed/audit/progress), unchanged Feature Extraction extract_rewritten_feature_set with fresh per-repeat cache roots and full original Qwen protocol, unchanged evaluate_task/validate_source/validate_curves/cluster bootstrap. Each measured task binds exact rewrite/plan hashes, ordered scene IDs, original feature file hashes and record-level protocol/features.\n\n'
    text += 'T03-A reports 48 tasks per CG repeat; T03-B uses only the same 12 matched task IDs in both conditions, with CG reused. T03-C reports TI successes/5, DA SD and gain distributions, failure counts, exact duplicate text hashes, pairwise token-set Jaccard and length variation. Conditional metrics and failure-zero ATI/ADA are separate; missing distances are never fabricated. Five repetitions are retained inside each base-interval bootstrap cluster (48 A / 12 B). Canonical PCG64 seed42 / 10000 resamples / 95% percentile-linear uncertainty estimates pooled observation-weighted means; mean/SD of repetition means is separately descriptive (sample SD ddof1, defined-repetition count). No p-values or significance claims.\n\n'
    text += '## Validation and delivery\n\nOffline tests:\n```json\n' + json.dumps(config['offline_tests'], indent=2) + '\n```\n\nSource changes:\n```json\n' + json.dumps(changed, indent=2) + '\n```\n\nExact commits:\n```json\n' + json.dumps(config['source_commits'], indent=2) + '\n```\n\nOutput locations:\n```json\n' + json.dumps(config['roots'], indent=2) + '\n```\n\n'
    text += 'Live progress uses the existing ProgressReporter: completed/total, percentage, elapsed/observed ETA HH:MM:SS, success/failure counts and scene throughput. Canonical task failures are printed immediately and retained; stage logs are exclusive files. Overall progress is shown between repetitions. Persistent servers never switch automatically. Strict live process argv/executable, port, model path/alias/SHA, slot/context checks precede inference. Complete primary/measurement request context checks occur only in author stages.\n\n'
    text += 'Interruption/unexpected errors preserve artifacts and incomplete stage receipts, blocking all further commands until an explicit recovery decision. No resume/overwrite bypass. Expected scientific generation/measurement failures remain in the full planned ledger and do not disappear between stages. Finished output trees are hash-sealed; later stages refuse mutations.\n\n'
    capped = [{k: p[k] for k in ('condition', 'task_id', 'scene_id', 'source_characters')} for p in read(config['primary_requests']) if p['historical_12000_character_cap_applied']]
    text += 'Known limitations: seeded Vulkan generation is controlled sampling, not a guarantee of bitwise reproducibility across hardware/runtime changes; identical outputs are possible and retained. Historical 12000-character scene cap remains unchanged in canonical prompt rendering; affected positions: ' + json.dumps(capped) + '. Live tokenizer/context capacity and actual inference viability remain author-run checks, not results of offline preparation. Twelve paired base intervals give limited precision; overlapping source windows and film clustering limit independence. No scientific results or experimental PASS is claimed. NOT_RUN CSV/Markdown tables are in the evaluation depot prepared_tables directory.\n\n' + commands
    (run / 'PREPARATION_REPORT.md').write_text(text)

def execute(action, run):
    if action == 'preflight':
        preflight(run)
        return
    config = load_config(run)
    if action.startswith('server-'):
        key = action.removeprefix('server-')
        server = config[key + '_server']
        if key == 'qwen':
            require_stage(run, 'VALIDATE_GENERATION')
        record = run / 'runtime' / ('SERVER_' + key.upper() + '.json')
        record.parent.mkdir(exist_ok=True)
        with record.open('x') as handle:
            json.dump(dict(pid=os.getpid(), command=server_command(server), model=config['models'][key]), handle)
        log = run / 'logs' / ('SERVER_' + key.upper() + '.log')
        log.parent.mkdir(exist_ok=True)
        with log.open('xb') as handle:
            os.dup2(handle.fileno(), 2)
        print('Author starting persistent ' + key + ' server; log ' + str(log), flush=True)
        os.execve(server['server_binary'], server_command(server), {k: v for k, v in os.environ.items() if not k.startswith('LLAMA_ARG_')})
    elif action in ('generate-cg', 'generate-dp'):
        if action == 'generate-dp':
            require_stage(run, 'GENERATE_CG')
        condition = 'CG-v1' if action == 'generate-cg' else 'DP-v1'
        sealed_stage(run, 'GENERATE_CG' if condition == 'CG-v1' else 'GENERATE_DP', lambda: generation(config, condition))
    elif action == 'validate-generation':
        require_stage(run, 'GENERATE_CG')
        require_stage(run, 'GENERATE_DP')

        def validate():
            output = run / 'validation'
            output.mkdir(exist_ok=False)
            write(output / 'GENERATION_VALIDATION.json', validate_generation(config))
            return [output]
        sealed_stage(run, 'VALIDATE_GENERATION', validate)
    elif action == 'reanalyze':
        require_stage(run, 'VALIDATE_GENERATION')
        require_stage(run, 'GENERATE_CG')
        require_stage(run, 'GENERATE_DP')
        sealed_stage(run, 'REANALYZE', lambda: reanalysis(config))
    elif action == 'evaluate':
        require_stage(run, 'REANALYZE')
        require_stage(run, 'GENERATE_CG')
        require_stage(run, 'GENERATE_DP')
        from storygen_evaluation.repeatability import evaluate
        sealed_stage(run, 'EVALUATE', lambda: [evaluate(config)])
