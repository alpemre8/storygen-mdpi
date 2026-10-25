"""Additive DP36 preparation and explicit author stages for E03 DP48.

Original E03 artifacts/code are read-only. No stage generates CG or old DP12.
prepare/finalize/preflight never contact a server or perform inference.
"""
from .technical import Tee, checked, context_check, fingerprints, live_runtime, read, require_stage, sealed_stage, server_command, sha, verified_live, verify_files, verify_port_owner, write
from .bindings import REWRITE, imports, git
from collections import Counter
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
from .bindings import REWRITE, imports
from .technical import read, write, sha, git, context_check, server_command
from .technical import fingerprints, verify_files, require_stage, verified_live, sealed_stage, Tee
from .repetition_api import validate_generation, generation, load_config as load_frozen_config

def load_extension_config(run):
    if read(run / 'CONFIG.json').get('contract') != 'storygen.E03.DP48-extension/1.0':
        raise RuntimeError('Only a fresh DP48 extension root is accepted; original E03 is read-only')
    return load_frozen_config(run)

def extension_population(cg_tasks, original_dp_ids):
    ids = [t['task_id'] for t in cg_tasks]
    if len(ids) != 48 or len(set(ids)) != 48 or len(original_dp_ids) != 12 or (len(set(original_dp_ids)) != 12) or (not set(original_dp_ids) <= set(ids)):
        raise RuntimeError('Frozen original CG48/DP12 selection mismatch')
    missing = [t for t in cg_tasks if t['task_id'] not in original_dp_ids]
    lengths = Counter((t['interval_type'] for t in missing))
    if len(missing) != 36 or lengths != {'short': 12, 'medium': 12, 'long': 12} or sum((len(t['source_scene_ids']) for t in missing)) != 300:
        raise RuntimeError('Frozen extension count/length/scene scope mismatch; STOP')
    return missing

def snapshot_original(original):
    """Read-only snapshot before any source/preparation modifications."""
    config = read(original / 'CONFIG.json')
    workspace = Path(config['workspace'])
    states = {repo: dict(head=git(workspace / repo, 'rev-parse', 'HEAD'), status=git(workspace / repo, 'status', '--porcelain')) for repo in config['source_commits']}
    if any((v['status'] for v in states.values())):
        raise RuntimeError('Snapshot requires clean source worktrees')
    protected = fingerprints([Path(p) for p in config['roots'].values()])
    protected.update(config['protected'])
    path = Path('/tmp') / ('E03_DP48_before_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json')
    write(path, dict(original_root=str(original), original_config_sha256=sha(original / 'CONFIG.json'), protected=protected, repositories=states))
    return path

def verify_original(original, before):
    config = read(original / 'CONFIG.json')
    workspace = Path(config['workspace'])
    imports(workspace)
    from storygen_evaluation.dp48_extension import verify_original_records
    from storygen.rewrite_v1_3.repeatability import request_seed, SEED_SCHEDULE
    if before['original_root'] != str(original) or sha(original / 'CONFIG.json') != before['original_config_sha256'] or sha(original / 'CONFIG.json') != (original / 'CONFIG.sha256').read_text().strip():
        raise RuntimeError('Original E03 config identity/seal mismatch')
    verify_files(before['protected'])
    verify_files(config['protected'])
    roots = [Path(p) for p in config['roots'].values()]
    old_files = {p for p in before['protected'] if any((Path(p).is_relative_to(root) for root in roots))}
    current = {str(p) for root in roots for p in root.rglob('*') if p.is_file()}
    if current != old_files:
        raise RuntimeError('Original E03 protected file inventory changed')
    for repo, revision in config['source_commits'].items():
        git(workspace / repo, 'merge-base', '--is-ancestor', revision, 'HEAD')
    for stage in ('GENERATE_CG', 'GENERATE_DP', 'VALIDATE_GENERATION', 'REANALYZE', 'EVALUATE'):
        require_stage(original, stage)
    validate_generation(config)
    if config['seed_schedule'] != SEED_SCHEDULE or read(original / 'manifests/REQUEST_SEEDS.json')['schedule'] != SEED_SCHEDULE:
        raise RuntimeError('Original request seed schedule incompatible')
    for row in read(original / 'manifests/REQUEST_SEEDS.json')['requests']:
        for attempt, key in [(1, 'primary_seed'), (2, 'repair_seed')]:
            if row[key] != request_seed(row['condition'], row['repetition_id'], row['task_id'], row['scene_id'], attempt):
                raise RuntimeError('Original E03.seed.v1 derivation incompatible')
    result = verify_original_records(config)
    result.update(original_root=str(original), source_commits=config['source_commits'], config_sha256=sha(original / 'CONFIG.json'), protected_file_count=len(before['protected']))
    return (config, result)

def prepare(original, before_path):
    before = read(before_path)
    old, verification = verify_original(original, before)
    workspace = Path(old['workspace'])
    imports(workspace)
    from storygen.rewrite_v1_3.repeatability import request_seed, SEED_SCHEDULE, payload_for
    from storygen.rewrite_v1_3.provenance import sha256_json, prompt_provenance
    from storygen.services import per_scene_rewrite_engine as engine
    from storygen.services.rewrite_engine import load_selected_scenes
    from storygen.schemas.transfer import TransferPlan
    from storygen_evaluation.provenance import structure_sha, validate_runtime, ArtifactResolver
    cg_runtime = read(old['tasksets']['CG-v1'])
    cg = cg_runtime['tasks']
    original_selection = read(original / 'manifests/SELECTION.json')
    cg_ids = original_selection['conditions']['CG-v1']['task_ids']
    dp_ids = original_selection['conditions']['DP-v1']['task_ids']
    if [t['task_id'] for t in cg] != cg_ids or read(old['tasksets']['DP-v1'])['tasks'] != [t for t in cg if t['task_id'] in dp_ids]:
        raise RuntimeError('Original selection/config/task projection mismatch')
    missing = extension_population(cg, dp_ids)
    for key, model in old['models'].items():
        if sha(model['path']) != model['sha256']:
            raise RuntimeError('Actual checkpoint SHA mismatch: ' + key)
    for execution in old['executions']['DP-v1']:
        manifest = read(Path(execution['generation']) / 'rewrite_run_manifest.json')
        if manifest['server_manifest']['content'] != old['gemma_server'] or manifest['decoding'] != old['decoding']:
            raise RuntimeError('Original DP generation settings disagree')
    for condition in ('DP-v1', 'CG-v1'):
        if prompt_provenance(REWRITE / 'rewrite', condition) != old['prompt_provenance'][condition]:
            raise RuntimeError('Original DP/CG prompt provenance changed')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    roots = {key: workspace / (repo + '-depot') / 'runs/reviewer_round1/E03_DP48_extension' / stamp for key, repo in [('rewrite', 'storygen-rewrite'), ('feature', 'storygen-feature-extraction'), ('evaluation', 'storygen-evaluation')]}
    for root in roots.values():
        root.mkdir(parents=True, exist_ok=False)
    run = roots['rewrite']
    write(run / 'manifests/BEFORE_CHANGES.json', before)
    write(run / 'manifests/ORIGINAL_VERIFICATION.json', verification)
    projection = {**cg_runtime, 'tasks': missing, 'structure_sha256': structure_sha(missing), 'e03_extension_of': str(original), 'e03_projection': 'Only original CG48 minus completed DP12; no new selection'}
    validate_runtime(projection, read(old['reference']['path']), Path(old['reference']['path']), ArtifactResolver())
    write(run / 'inputs/DP36_RUNTIME.json', projection)
    for task in missing:
        source = Path(old['frozen_plans']) / 'tasks' / task['task_id'] / 'transfer_plan.json'
        destination = run / 'inputs/frozen_plans/tasks' / task['task_id'] / 'transfer_plan.json'
        destination.parent.mkdir(parents=True)
        shutil.copy2(source, destination)
    primary = []
    system = (REWRITE / 'rewrite/prompts/direct_prompt_system_v1.txt').read_text()
    for task in missing:
        plan = TransferPlan.model_validate(read(run / 'inputs/frozen_plans/tasks' / task['task_id'] / 'transfer_plan.json'))
        scenes = load_selected_scenes(task['source_script_path'], task['source_scene_ids'])
        for index, (scene, directive) in enumerate(zip(scenes, plan.per_scene_target_values)):
            prompt = engine.build_per_scene_direct_prompt(scene=scene, directive=directive, plan=plan, scene_position_index=index, scene_count=len(scenes), max_scene_chars=12000)
            payload = payload_for(prompt, old['gemma_server']['model_alias'], system=system, format_schema=engine.one_scene_rewrite_schema_for(scene.scene_id), options={'temperature': 0.2, 'max_tokens': 4096})
            primary.append(dict(condition='DP-v1', task_id=task['task_id'], base_interval_id=task['base_interval_id'], scene_id=scene.scene_id, prompt_hash=sha256_json(payload['messages']), request_contract_hash=sha256_json(payload), payload=payload, source_characters=len(scene.content), historical_12000_character_cap_applied=len(scene.content) > 12000))
    if len(primary) != 300:
        raise RuntimeError('DP36 frozen primary prompt count mismatch')
    write(run / 'inputs/PRIMARY_REQUESTS.json', primary)
    seed_rows = [dict(condition='DP-v1', repetition_id=rep, task_id=p['task_id'], scene_id=p['scene_id'], primary_seed=request_seed('DP-v1', rep, p['task_id'], p['scene_id'], 1), repair_seed=request_seed('DP-v1', rep, p['task_id'], p['scene_id'], 2)) for p in primary for rep in range(1, 6)]
    old_seeds = read(original / 'manifests/REQUEST_SEEDS.json')['requests']
    all_seeds = [r[key] for r in old_seeds + seed_rows for key in ('primary_seed', 'repair_seed')]
    if len(seed_rows) != 1500 or len(set(all_seeds)) != 8000:
        raise RuntimeError('Seed uniqueness/compatibility mismatch; STOP')
    write(run / 'manifests/REQUEST_SEEDS.json', dict(protocol='E03.seed.v1', schedule=SEED_SCHEDULE, requests=seed_rows, compatible_original_manifest=dict(path=str(original / 'manifests/REQUEST_SEEDS.json'), sha256=sha(original / 'manifests/REQUEST_SEEDS.json')), global_primary_and_potential_repair_seed_count=8000, global_unique_seed_count=8000))
    populations = {'CG-v1': cg_ids, 'DP-original-12': dp_ids, 'DP-extension-36': [t['task_id'] for t in missing]}
    write(run / 'manifests/POPULATIONS.json', dict(populations=populations, selection_method='Frozen set difference only; no performance selection', lengths=dict(Counter((t['interval_type'] for t in missing))), features=dict(Counter((t['selected_features'][0] for t in missing))), source_films=dict(Counter((t['source_film_id'] for t in missing))), repetitions=5, new_primary_requests=1500, new_task_repetitions=180, full_planned_per_condition=240, full_planned_observations=480))
    for key in ('gemma', 'qwen'):
        write(run / f'manifests/{key.upper()}_SERVER.json', old[key + '_server'])
    write(run / 'P01.json', dict(P01='PASS', original_root=str(original), roots={k: str(v) for k, v in roots.items()}, populations=populations, verification=verification, models=old['models'], scientific_results='NOT_RUN'))
    print('P01 PASS: ' + str(run))
    return run

def finalize(run, tests_path):
    if (run / 'CONFIG.json').exists():
        raise FileExistsError('Extension already finalized')
    p01 = read(run / 'P01.json')
    original = Path(p01['original_root'])
    before = read(run / 'manifests/BEFORE_CHANGES.json')
    old, verification = verify_original(original, before)
    workspace = Path(old['workspace'])
    imports(workspace)
    from storygen_evaluation.dp48_extension import prepare_tables
    from storygen_evaluation.provenance import structure_sha
    from storygen.rewrite_v1_3.repeatability import generation_records
    tests = read(tests_path)
    if tests['failed'] != 0 or tests['skipped'] != 0 or tests['passed'] < 1:
        raise RuntimeError('Offline tests must PASS without skips')
    commits = {repo: git(workspace / repo, 'rev-parse', 'HEAD') for repo in old['source_commits']}
    if any((git(workspace / repo, 'status', '--porcelain') for repo in commits)):
        raise RuntimeError('Source worktrees must be clean')
    roots = {k: Path(p) for k, p in p01['roots'].items()}
    runtime = str(run / 'inputs/DP36_RUNTIME.json')
    tasksets = {'DP-v1': runtime}
    tasks = read(runtime)['tasks']
    config = {k: old[k] for k in ('workspace', 'reference', 'frozen_taskset', 'models', 'measurement', 'decoding', 'gemma_server', 'qwen_server', 'binary_sha256', 'seed_schedule')}
    config.update(contract='storygen.E03.DP48-extension/1.0', experiment_id=run.name, roots=p01['roots'], populations=p01['populations'], original_root=str(original), source_commits=commits, tasksets=tasksets, selection={'conditions': {'DP-v1': dict(task_ids=[t['task_id'] for t in tasks], projection_structure_sha256=structure_sha(tasks))}}, gemma_manifest=str(run / 'manifests/GEMMA_SERVER.json'), qwen_manifest=str(run / 'manifests/QWEN_SERVER.json'), primary_requests=str(run / 'inputs/PRIMARY_REQUESTS.json'), frozen_plans=str(run / 'inputs/frozen_plans'), prompt_provenance={'DP-v1': old['prompt_provenance']['DP-v1']}, offline_tests=tests, executions={'DP-v1': [dict(repetition_id=rep, generation=str(run / 'generation/DP-v1' / f'repeat_{rep:02d}'), reanalysis=str(roots['feature'] / 'reanalysis/DP-v1' / f'e03_dp48_{run.name}_repeat_{rep:02d}_fev1_4')) for rep in range(1, 6)]}, evaluation_output=str(roots['evaluation'] / 'evaluation/T03_FULL48'), history={'records': verification['records'], 'bindings': verification['bindings'], 'text_diagnostics': dict(path=str(Path(old['evaluation_output']) / 'TEXT_VARIABILITY.csv'), sha256=sha(Path(old['evaluation_output']) / 'TEXT_VARIABILITY.csv'))})
    ledger = []
    for e in config['executions']['DP-v1']:
        ledger.extend([{**r, 'completion_status': 'NOT_RUN', 'failure_reason': None, 'output_hash': None} for r in generation_records(config, 'DP-v1', e['repetition_id'], Path(e['generation']))])
    write(run / 'manifests/PLANNED_NEW_EXECUTIONS.json', ledger)
    prepare_tables(roots['evaluation'] / 'prepared_tables', config['populations']['CG-v1'])
    protected = dict(before['protected'])
    protected.update(fingerprints([run / 'inputs', run / 'manifests']))
    protected[str(run / 'P01.json')] = sha(run / 'P01.json')
    for repo in commits:
        for name in git(workspace / repo, 'ls-files').splitlines():
            path = workspace / repo / name
            if path.is_file():
                protected[str(path)] = sha(path)
    config['protected'] = protected
    write(run / 'CONFIG.json', config)
    (run / 'CONFIG.sha256').write_text(sha(run / 'CONFIG.json') + '\n')
    preflight(run)
    commands = author_commands(run)
    (run / 'AUTHOR_COMMANDS.md').write_text(commands)
    preparation_report(run, config, before, verification, commands)
    write(run / 'OFFLINE_GATES.json', dict(P01='PASS', P02='PASS', P03='PASS', status='IMPLEMENTATION_READY', original_E03='PRESERVED', canonical_pipeline='UNCHANGED', scientific_results='NOT_RUN', human_execution='PENDING', new_DP_tasks=36, repetitions=5, new_primary_generation=1500, new_Qwen_measurements_max=1500, new_CG_generation=0, protected_files=len(protected), tests=tests))
    for key, root in roots.items():
        if key != 'rewrite':
            write(root / 'PREPARATION_LINK.json', dict(config=str(run / 'CONFIG.json'), report=str(run / 'PREPARATION_REPORT.md')))
    print('E03_DP48_EXTENSION IMPLEMENTATION_READY: ' + str(run))

def preflight(run):
    config = load_extension_config(run)
    old, verification = verify_original(Path(config['original_root']), read(run / 'manifests/BEFORE_CHANGES.json'))
    from storygen_evaluation.provenance import validate_runtime, validate_curves, ArtifactResolver
    from storygen_measurement_core import MeasurementProtocol
    from storygen_measurement_core.preflight import validate_runtime_identity
    missing = extension_population(read(old['tasksets']['CG-v1'])['tasks'], config['populations']['DP-original-12'])
    tasks = read(config['tasksets']['DP-v1'])['tasks']
    if tasks != missing or len(read(run / 'manifests/PLANNED_NEW_EXECUTIONS.json')) != 180 or len(read(config['primary_requests'])) != 300:
        raise RuntimeError('Frozen DP36 extension scope mismatch')
    reference = read(config['reference']['path'])
    path = Path(config['reference']['path'])
    validate_runtime(read(config['tasksets']['DP-v1']), reference, path, ArtifactResolver())
    validate_curves(tasks, Path(config['frozen_plans']), Path(config['frozen_plans']), path, reference, ArtifactResolver())
    protocol = MeasurementProtocol.load(Path(config['workspace']) / 'storygen-feature-extraction/measurement', 'configs/feature_measurement_v1.yaml')
    if protocol.manifest() != config['measurement'] or config['measurement'] != old['measurement']:
        raise RuntimeError('Original Qwen full protocol mismatch')
    validate_runtime_identity(protocol, model_file=config['models']['qwen']['path'], server_manifest=config['qwen_manifest'], require_slots=8)
    print('P01/P02/P03 offline preflight PASS; original 300 observations verified; extension NOT_RUN', flush=True)
    return config

def generate_extension(config):
    outputs = generation(config, 'DP-v1')
    for output in outputs:
        records = read(output / 'E03_EXECUTIONS.json')
        for row in records:
            file = Path(row['output_path']) / 'rewritten_scenes.json'
            row.update(model_sha256=row['checkpoint_sha256'], generation_status=row['completion_status'], sampling_seed=row['primary_seeds'], output_hash=sha(file) if file.is_file() else None)
        path = output / 'DP48_EXECUTIONS.json'
        with path.open('x') as handle:
            json.dump(records, handle, indent=2)
    return outputs

def reanalyze_extension(config):
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
    tasks = read(config['tasksets']['DP-v1'])['tasks']
    outputs = []
    for execution in config['executions']['DP-v1']:
        rewrite = Path(execution['generation'])
        output = Path(execution['reanalysis'])
        prompts = []
        if output.exists():
            raise FileExistsError('Extension does not resume/overwrite reanalysis')
        for task in tasks:
            td = rewrite / 'tasks' / task['task_id']
            if (td / 'phase_status.json').is_file() and read(td / 'phase_status.json').get('rewrite_completed') is True:
                for scene in read(td / 'rewritten_scenes.json')['rewritten_scenes']:
                    prompts.append(build_request_payload(prompt=scorer._render(task['source_film_id'], scene['scene_id'], scene['title'], scene['content']), model=protocol.model['alias'], schema=protocol.schema, decoding=protocol.decoding, system_instruction=protocol.system_instruction, response_schema_name=protocol.response_schema_name))
        context_check(url, prompts, 256, 12288)
        print(f'Qwen DP36 repeat {execution['repetition_id']}/5: available complete-task positions {len(prompts)}/300; original CG/DP12 excluded', flush=True)
        try:
            extract_rewritten_feature_set(project_root=feature, core_root=core, protocol_path=Path('configs/feature_measurement_v1.yaml'), rewrite_run=rewrite, reference_feature_set_manifest=Path(config['reference']['path']), taskset_runtime=Path(config['tasksets']['DP-v1']), feature_set_id=output.name, output_root=output.parent, model_file=Path(config['models']['qwen']['path']), server_manifest=Path(config['qwen_manifest']), concurrency=8, progress_mode='always')
        except RuntimeError as exc:
            manifest = output / 'feature_set_manifest.json'
            if not manifest.is_file() or str(exc) != f'{read(manifest)['tasks_failed']} rewritten Feature Extraction tasks failed; valid artifacts were preserved':
                raise
            print('\nCanonical measurement failures retained: ' + str(exc), flush=True)
        outputs.append(output)
        print(f'Extension reanalysis repeats completed {len(outputs)}/5', flush=True)
    return outputs

def author_commands(run):
    command = f'/home/alp-emre/.venv/bin/python3 {REWRITE}/tools/e03_dp48_extension.py'
    return '# E03 DP48 extension author commands\n\nOnly the author runs inference. Original E03 is read-only.\n\nIn both terminals:\n```bash\n' + f'RUN={str(run)!r}\next03() {{ {command} "$1" --run "$RUN"; }}\n```\n\nTerminal 2, before starting a model:\n```bash\next03 preflight\n```\n\nTerminal 1 (persistent Gemma):\n```bash\next03 server-gemma\n```\n\nTerminal 2:\n```bash\next03 generate-dp-extension\next03 validate-extension\n```\n\nAfter validation, the author stops Gemma with Ctrl+C in Terminal 1 and starts Qwen:\n```bash\next03 server-qwen\n```\n\nTerminal 2:\n```bash\next03 reanalyze-extension\next03 evaluate-extended\n```\n\nNo CG or original DP12 inference stage exists here. Each stage is explicit. No automatic overwrite, resume, server restart or model switching. An incomplete stage receipt blocks further commands; preserve outputs and obtain an explicit author recovery decision. This tool provides no recovery bypass. Existing server receipts cannot be replaced. Source/model/input/history changes stop execution. Complete primary and measurement prompts are checked by the live tokenizer before inference with the frozen context unchanged.\n'

def preparation_report(run, config, before, verification, commands):
    old = read(Path(config['original_root']) / 'CONFIG.json')
    changes = {repo: git(Path(config['workspace']) / repo, 'diff', '--name-only', v['head'], config['source_commits'][repo]).splitlines() for repo, v in before['repositories'].items()}
    report = '# E03 DP48 additive extension preparation\n\nIMPLEMENTATION_READY. P01/P02/P03 PASS. Original E03 PRESERVED. Canonical pipeline UNCHANGED. Extension scientific results NOT_RUN; human execution PENDING.\n\n'
    report += 'Objective: match original CG48 with the same DP48 across the same five repetition indices. Reuse 240 CG and 60 old DP observations, append only 180 new DP36 observations; final planned ledger 480, 240 per condition, 48 distinct base intervals.\n\n'
    for name, ids in config['populations'].items():
        report += f'## {name}\n\n' + ', '.join(ids) + '\n\n'
    report += 'Selection is strictly the frozen set difference CG_original_48 minus DP_original_12. No new scientific population or outcome-based selection. DP36 is 12 short/12 medium/12 long, 300 source positions per repeat; five repeats = 1500 new primary Gemma requests (repairs additional). Maximum new Qwen scope 1500; only complete canonical successful tasks are eligible for measurement. No original CG/DP12/source/reference remeasurement or generation.\n\n'
    report += 'Original verification:\n```json\n' + json.dumps(verification, indent=2) + '\n```\n\nOriginal generation/reanalysis/evaluation roots and immutable references:\n```json\n' + json.dumps(dict(roots=old['roots'], config_path=str(Path(config['original_root']) / 'CONFIG.json'), config_sha256=sha(Path(config['original_root']) / 'CONFIG.json'), tasksets=old['tasksets'], executions=old['executions'], history=config['history']), indent=2) + '\n```\n\n'
    report += 'All original stage receipts are COMPLETE and their output checksums verified. Original configuration seal, full file inventory and pre-edit fingerprints are preserved. All 300 old task records and bindings match canonical artifact/measurement/metric verification; old records are appended verbatim, including their failures. No failed old observation is retried or replaced.\n\n'
    report += 'Preservation: all previously tracked source files, DP/CG/system/repair assets, canonical engine/scheduler/transport/schemas/normalizers/preservation validators, scorer/protocol/targets, metric and bootstrap source are unchanged. Only new experiment-level source files are added. Frozen transfer plans are copied byte-for-byte from original inputs; no target reconstruction. New DP prompts use the unchanged DP-v1 renderer and historical 12000-character cap. Primary prompts/settings are hashed before inference and checked by the existing E03 request tracer.\n\n'
    report += 'Model/settings provenance:\n```json\n' + json.dumps({key: config[key] for key in ('models', 'decoding', 'gemma_server', 'qwen_server', 'seed_schedule')}, indent=2) + '\n```\n\n'
    report += 'Seeds: unchanged E03.seed.v1 implementation and DP masters 44001–44005. Request seed uses the original condition/task/scene/attempt identity; all original planned seeds match the current frozen implementation. Original and extension primary/potential-repair seeds are globally unique (8000 total). Actual seeds are audited at the same OpenAI JSON seed location; prompts are never modified for variation. No response caches reused. Persistent Vulkan model loading, continuous batching, four Gemma slots and eight Qwen slots retain original behavior.\n\n'
    report += 'Evaluation: original analysis/metrics/bootstrap kernels reused on equal 48-task populations, strictly paired task_id+repetition_id. ATI/ADA_all retain all 240 per-condition observations; conditional and paired-measurable populations and coverage/failures are separate. Missing gains are never imputed. Bootstrap samples base intervals while retaining repeat bundles: 10000 NumPy PCG64(default_rng(42)) draws, 95% percentile linear. Forty-eight planned clusters; represented measurable cluster counts reported. Repetition sample SD (ddof1) is descriptive and separate from pooled observation-weighted cluster uncertainty. Existing exact-text hashes, token-set Jaccard and character distributions are reused for old tasks and computed identically for new tasks. No p-values/significance claims.\n\n'
    report += 'Offline tests:\n```json\n' + json.dumps(config['offline_tests'], indent=2) + '\n```\n\nChanged source files:\n```json\n' + json.dumps(changes, indent=2) + '\n```\n\nSource commits:\n```json\n' + json.dumps(config['source_commits'], indent=2) + '\n```\n\nNew isolated roots:\n```json\n' + json.dumps(config['roots'], indent=2) + '\n```\n\nExtended T03 runtime output: ' + config['evaluation_output'] + '. NOT_RUN CSV/Markdown tables are under ' + str(Path(config['roots']['evaluation']) / 'prepared_tables') + '.\n\n'
    report += 'Progress uses unchanged E03 generation tracing/ProgressReporter and the canonical measurement scheduler: completed/total, percent, elapsed/observed ETA HH:MM:SS, success/failure, throughput. Overall repeats are accurately reported out of five. Task/scene failures are printed and retained. Outputs/logs/receipts are exclusive; no implicit resume/overwrite. Interrupted/unexpected failed stages block all further stages pending an explicit recovery decision. Existing in-flight requests follow canonical shutdown behavior. Completed stages are hash-sealed before downstream use.\n\n'
    report += 'Known limits: complete request context and actual inference viability are author checks. The historical scene cap is preserved. Controlled Vulkan seeds do not ensure bitwise portability across hardware changes; identical outputs remain valid and audited. Window/film dependence and failure-dependent missingness remain; negative results are retained. This preparation creates no new scientific observations.\n\n' + commands
    (run / 'PREPARATION_REPORT.md').write_text(report)

def execute(action, run):
    if action == 'preflight':
        preflight(run)
        return
    config = load_extension_config(run)
    verify_original(Path(config['original_root']), read(run / 'manifests/BEFORE_CHANGES.json'))
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
    elif action == 'generate-dp-extension':
        sealed_stage(run, 'GENERATE_DP', lambda: generate_extension(config))
    elif action == 'validate-extension':
        require_stage(run, 'GENERATE_DP')

        def validate():
            rows = validate_generation(config)
            output = run / 'validation'
            output.mkdir(exist_ok=False)
            write(output / 'EXTENSION_VALIDATION.json', rows)
            return [output]
        sealed_stage(run, 'VALIDATE_GENERATION', validate)
    elif action == 'reanalyze-extension':
        require_stage(run, 'GENERATE_DP')
        require_stage(run, 'VALIDATE_GENERATION')
        sealed_stage(run, 'REANALYZE', lambda: reanalyze_extension(config))
    elif action == 'evaluate-extended':
        require_stage(run, 'GENERATE_DP')
        require_stage(run, 'VALIDATE_GENERATION')
        require_stage(run, 'REANALYZE')
        from storygen_evaluation.dp48_extension import evaluate_extended
        sealed_stage(run, 'EVALUATE', lambda: [evaluate_extended(config)])

def action_requires_log(action):
    return action in ('generate-dp-extension', 'validate-extension', 'reanalyze-extension', 'evaluate-extended')
