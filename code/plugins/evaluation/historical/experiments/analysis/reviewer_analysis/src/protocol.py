"""P01B deterministic analysis of immutable paper inputs with exact provider API."""
from pathlib import Path
import sys
REQUIRED_CONFIG = {'inputs': ['analysis_plan', 'test_results'], 'purpose': 'RESEARCH or MIGRATION_VERIFICATION', 'optional': 'inputs.artifact_paths contains exact historical path overrides', 'inference': 'NONE; all original scientific and test-receipt gates remain enforced'}

def plan(c):
    command = [sys.executable, str(c.repo / 'components/evaluation/v2_4_1/reviewer_provider.py'), '--provider-root', str(c.source('storygen-evaluation')), '--analysis-plan', c.input('analysis_plan'), '--test-results', c.input('test_results'), '--output', str(c.output('storygen-evaluation', 'analyze'))]
    if 'artifact_paths' in c.config['inputs']: command += ['--artifact-paths', c.input('artifact_paths')]
    return [dict(stage_id='analyze', provider_repo='storygen-evaluation', command=command)]
