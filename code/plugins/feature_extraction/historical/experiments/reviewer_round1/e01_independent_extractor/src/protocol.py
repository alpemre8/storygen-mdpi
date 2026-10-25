"""Strict independent E01A qualification; no alternate scientific implementation."""
REQUIRED_CONFIG = {'inputs': ['profile', 'input_contract', 'selection'], 'purpose': 'RESEARCH or MIGRATION_VERIFICATION', 'server': 'Exact bound E01 FP16 profile; manage_servers=true owns its frozen argv, false uses an external server'}

def plan(c):
    output = c.output('storygen-feature-extraction', 'qualify')
    command = c.command('storygen-feature-extraction', 'feature_extraction/cli/qualify_independent_extractor.py', 'smoke', '--profile', c.input('profile'), '--input-contract', c.input('input_contract'), '--selection', c.input('selection'), '--output-dir', output, '--execute-inference')
    if c.config.get('manage_servers', False):
        import sys
        version=c.config.get('technical_runtime_version','v1')
        if version not in {'v1','v2'}:raise ValueError('Explicit known E01 technical runtime version required')
        command=[sys.executable,str(c.repo/('components/measurement/e01_runtime/'+version+'/qualify_owned.py')),'--provider-root',str(c.source('storygen-feature-extraction')),'--profile',c.input('profile'),'--input-contract',c.input('input_contract'),'--selection',c.input('selection'),'--output',str(output),'--server-log',str(c.root('storygen-feature-extraction')/'logs/e01_server.log')]
    return [dict(stage_id='qualify', provider_repo='storygen-feature-extraction', command=command)]
