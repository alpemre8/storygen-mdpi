"""Historical TasksetV5 recipe; all scientific stages call frozen provider CLIs."""
import json
from pathlib import Path

REQUIRED_CONFIG = {
    'purpose': 'RESEARCH or MIGRATION_VERIFICATION',
    'inputs': ['film_set', 'reference_feature_set', 'rewrite_server_manifest', 'measurement_server_manifest'],
    'input_root': 'Immutable films input directory belonging to the frozen original measurements',
    'strategy': 'DP-v1 or CG-v1',
    'verification_task_ids': 'Optional whole-task subset; permitted only for MIGRATION_VERIFICATION',
    'manage_servers': 'true starts/stops only owned persistent exact-profile llama.cpp processes; false uses external servers',
}


def plan(c):
    rw, fe, ev = 'storygen-rewrite', 'storygen-feature-extraction', 'storygen-evaluation'
    reference = c.input('reference_feature_set')
    manifest = json.loads(Path(reference).read_text())
    strategy = c.config['strategy']
    if strategy not in {'DP-v1', 'CG-v1'}:
        raise ValueError('Frozen TasksetV5 supports only DP-v1/CG-v1')
    profiles = json.loads((c.repo / 'components/tasksetv5/v1/SERVER_PROFILES.json').read_text())
    rewrite = json.loads(Path(c.input('rewrite_server_manifest')).read_text())
    measurement = json.loads(Path(c.input('measurement_server_manifest')).read_text())
    if rewrite not in profiles['rewrite'] or measurement != profiles['measurement']:
        raise ValueError('Runtime differs from the frozen historical model profile')
    feature_id = manifest['feature_set_id']
    full = c.output(rw, 'build_taskset') / 'taskset_v5/runtimes' / feature_id / 'taskset_runtime.json'
    runtime = c.output(rw, 'bind_runtime') / 'taskset_runtime.json'
    rewrite_id = 'tasksetv5_rwv1_3_' + c.run_id + '_' + strategy
    rewritten = c.output(rw, 'rewrite') / rewrite_id
    measured_id = 'fs_fev1_4_' + c.run_id
    measured = c.output(fe, 'remeasure') / measured_id
    stages = [dict(stage_id='build_taskset', provider_repo=rw, command=c.command(rw,
        'taskset/cli/build_taskset_runtime.py', '--film-set', c.input('film_set'), '--input-root', c.config['input_root'],
        '--feature-set-manifest', reference, '--feature-set-root', Path(reference).parent,
        '--output-root', c.output(rw, 'build_taskset')))]
    command = [__import__('sys').executable, str(c.repo / 'components/tasksetv5/v1/bind_runtime.py'),
        '--parent', str(full), '--output', str(runtime), '--purpose', c.config['purpose']]
    ids = c.config.get('verification_task_ids', [])
    if ids and c.config['purpose'] != 'MIGRATION_VERIFICATION':
        raise ValueError('Partial benchmark requests require MIGRATION_VERIFICATION purpose')
    for task_id in ids:
        command += ['--task-id', task_id]
    stages.append(dict(stage_id='bind_runtime', provider_repo=rw, command=command))
    stages.append(dict(stage_id='rewrite', provider_repo=rw, server_profile='rewrite_server_manifest',
        command=c.command(rw, 'rewrite/cli/run_taskset.py', '--taskset', runtime,
        '--feature-set-manifest', reference, '--run-id', rewrite_id, '--model', rewrite['model_alias'],
        '--model-file', rewrite['model_path'], '--quantization', rewrite['quantization'],
        '--server-manifest', c.input('rewrite_server_manifest'), '--strategy', strategy,
        '--output-root', c.output(rw, 'rewrite'), '--base-url', rewrite['base_url'],
        '--temperature', '0.2', '--schema-retry-count', '1', '--rewrite-max-tokens', '4096',
        '--rewrite-concurrency', rewrite['parallel_slots'], '--rewrite-timeout-seconds', rewrite['timeout_seconds'])))
    stages.append(dict(stage_id='remeasure', provider_repo=fe, server_profile='measurement_server_manifest',
        command=c.command(fe, 'feature_extraction/cli/extract_rewritten_feature_set.py',
        '--rewrite-run', rewritten, '--reference-feature-set-manifest', reference, '--taskset-runtime', runtime,
        '--feature-set-id', measured_id, '--output-root', c.output(fe, 'remeasure'),
        '--model-file', measurement['model_path'], '--server-manifest', c.input('measurement_server_manifest'),
        '--concurrency', '8')))
    stages.append(dict(stage_id='evaluate', provider_repo=ev, command=c.command(ev,
        'evaluation/cli/evaluate_run.py', '--taskset-runtime', runtime, '--feature-set-manifest', reference,
        '--candidate-feature-set', measured, '--output-run-id', 'evaluation_evv2_4_' + c.run_id,
        '--output-root', c.output(ev, 'evaluate'), '--method', strategy, '--rewrite-model', rewrite['model_alias'])))
    return stages
