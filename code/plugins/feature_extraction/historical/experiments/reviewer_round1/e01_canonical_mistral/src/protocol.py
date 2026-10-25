"""E01 canonical Mistral remeasurement; preserve generation lineage and method."""
from pathlib import Path
REQUIRED_CONFIG = {'inputs': ['reference_feature_set', 'taskset', 'dp_rewrite_manifest', 'cg_rewrite_manifest', 'server_manifest'], 'model_file': 'Exact locked Mistral F16 model', 'purpose': 'RESEARCH or MIGRATION_VERIFICATION', 'reference': 'Existing immutable original Mistral FeatureSet and its exact runtime; generation lineage remains Qwen'}

def plan(c):
    stages = []
    for stage, ref in [('remeasure_dp', 'dp_rewrite_manifest'), ('remeasure_cg', 'cg_rewrite_manifest')]:
        command = c.command('storygen-feature-extraction', 'feature_extraction/cli/extract_rewritten_feature_set.py', '--protocol', c.source('storygen-feature-extraction') / 'measurement/configs/feature_measurement_mistral_f16_v1.yaml', '--remeasure-existing-rewrites', '--rewrite-run', Path(c.input(ref)).parent, '--reference-feature-set-manifest', c.input('reference_feature_set'), '--taskset-runtime', c.input('taskset'), '--feature-set-id', 'fs_fev1_4_' + c.run_id + '_' + stage, '--output-root', c.output('storygen-feature-extraction', stage), '--model-file', c.config['model_file'], '--server-manifest', c.input('server_manifest'), '--concurrency', str(c.config.get('concurrency', 1)))
        job=dict(stage_id=stage, provider_repo='storygen-feature-extraction', command=command)
        if c.config.get('manage_servers', False):job['server_profile']='server_manifest'
        stages.append(job)
    return stages
