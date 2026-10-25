"""Independent frozen protocol recipe; scientific API bytes and selections are locked."""
import json
from pathlib import Path
import sys

PARAMS = {'slug': 'e02_no_guidance', 'module': 'no_guidance_api', 'parent_sha': 'sha256:54da56400126869d07f7027aaf692b5a061dfc62dd69b3436c42d99754f9fc78', 'actions': [('prepare', 'prepare', 'storygen-rewrite', None), ('preflight', 'preflight', 'storygen-rewrite', None), ('generate', 'stage-a', 'storygen-rewrite', 'gemma'), ('remeasure', 'stage-c', 'storygen-feature-extraction', 'qwen'), ('evaluate', 'stage-d', 'storygen-evaluation', None)]}
REQUIRED_CONFIG = {'inputs': ['parent_config', 'rewrite_server_manifest', 'measurement_server_manifest (for generation/FE protocols)'], 'purpose': 'RESEARCH or MIGRATION_VERIFICATION', 'manage_servers': 'true owns only exact frozen profiles; false requires explicit compatible live-server receipts', 'protocol': 'Exact archived sampling, repetition, prompts, repair policy and denominators; no historical outputs reused as new measurements'}

def plan(c):
    parent_path=Path(c.input('parent_config'))
    if c.config['inputs']['parent_config']['sha256']!=PARAMS['parent_sha']:
        raise ValueError('Parent scientific preparation differs from exact experiment lock')
    parent=json.loads(parent_path.read_text())
    if parent['source_commits']!={row['repo_id']:row['commit'] for row in c.lock['source_repositories']}:
        raise ValueError('Scientific provider source revisions differ from archived protocol')
    stages=[];rw='storygen-rewrite'
    for stage_id,action,provider,server_key in PARAMS['actions']:
        command=[sys.executable,str(c.repo/'components/protocol_replay/v1/launch.py'),
            '--bundle',str(c.repo/'components/reviewer_protocols'/PARAMS['slug']/'v1'),
            '--workspace',str(c.provider_workspace),'--backend-root',str(c.config.get('backend_root',c.workspace/'llama.cpp')),
            '--module',PARAMS['module'],'--action',action,'--protocol-root',str(c.root(rw)/'raw/protocol'),
            '--parent-config',str(parent_path),'--producer-roots',str(c.root(rw)/'inputs/producer_roots.json'),
            '--receipt-dir',str(c.output(provider,stage_id))]
        stage=dict(stage_id=stage_id,provider_repo=provider,command=command)
        if server_key:
            role='measurement_server_manifest' if server_key=='qwen' else 'rewrite_server_manifest'
            profile=json.loads(Path(c.input(role)).read_text());identity=c.runtime.canonical_sha256(profile)
            if identity not in c.lock['scientific_invariants']['allowed_server_profile_sha256']:
                raise ValueError('Server profile differs from frozen protocol')
            live=c.root(rw)/('inputs/live_server_'+identity[-12:]+'.json')
            if not c.config.get('manage_servers',False):
                live=Path(c.input('live_'+server_key+'_receipt'))
            command+=['--live-server-record',str(live),'--server-key',server_key]
            if server_key=='judge':command+=['--server-mode','four']
            stage['server_profile']=role
        stages.append(stage)
    return stages
