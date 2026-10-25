"""Frozen canonical reliability study; sample/denominators stay in the provider."""
REQUIRED_CONFIG = {'inputs': ['scene_manifest', 'server_manifest'], 'model_file': 'Exact Qwen canonical model', 'purpose': 'RESEARCH or MIGRATION_VERIFICATION', 'population': '100 unique scenes, 10 films, 10 scenes per film, 5 repeats; seed 42'}

def plan(c):
    command = c.command('storygen-feature-extraction', 'feature_extraction/cli/run_measurement_reliability.py', '--scene-manifest', c.input('scene_manifest'), '--output', c.output('storygen-feature-extraction', 'reliability'), '--model-file', c.config['model_file'], '--server-manifest', c.input('server_manifest'), '--repeats', '5', '--seed', '42', '--concurrency', str(c.config.get('concurrency', 8)))
    return [dict(stage_id='reliability', provider_repo='storygen-feature-extraction', command=command)]
