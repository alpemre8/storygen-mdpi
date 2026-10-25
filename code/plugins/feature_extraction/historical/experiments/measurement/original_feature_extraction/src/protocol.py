"""Canonical original-scene measurement through the frozen FE CLI."""
REQUIRED_CONFIG = {'inputs': ['film_set', 'server_manifest'], 'input_root': 'Absolute immutable films input root', 'model_file': 'Exact canonical model file', 'purpose': 'RESEARCH or MIGRATION_VERIFICATION', 'scene_selection': 'Optional exact inputs.scene_selection reference'}

def plan(c):
    key = 'measure'
    command = c.command('storygen-feature-extraction', 'feature_extraction/cli/extract_feature_set.py', '--film-set', c.input('film_set'), '--input-root', c.config['input_root'], '--feature-set-id', 'fs_fev1_4_' + c.run_id, '--output-root', c.output('storygen-feature-extraction', key), '--model-file', c.config['model_file'], '--server-manifest', c.input('server_manifest'), '--concurrency', str(c.config.get('concurrency', 8)))
    if 'scene_selection' in c.config['inputs']: command += ['--scene-selection', c.input('scene_selection')]
    return [dict(stage_id=key, provider_repo='storygen-feature-extraction', command=command)]
