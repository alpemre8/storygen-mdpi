"""Executable per-experiment DAG data; compatible public components or owned engines."""
from pathlib import Path
import json
import subprocess
import sys


def plan(c,definition):
    from jsonschema import Draft202012Validator
    Draft202012Validator(json.loads((c.home/'schemas/run_configuration.schema.json').read_text())).validate(c.config)
    if definition.get('synthetic_only') and c.config['purpose']!='SYNTHETIC_TEST':
        raise ValueError('Synthetic engines cannot produce research or migration measurements')
    if c.config['purpose']=='RESEARCH':
        # Actual research must be reproducible at a committed owner source identity.
        for ref in c.lock['assets']:
            if ref['root_id']=='owner':
                payload=subprocess.check_output(['git','-C',str(c.repo),'show','HEAD:'+ref['path']])
                import hashlib
                if 'sha256:'+hashlib.sha256(payload).hexdigest()!=ref['sha256']:
                    raise RuntimeError('Commit exact owner sources before a RESEARCH run: '+ref['path'])
    catalog=json.loads((c.repo/'components/scaffolding/v1/COMPONENT_CATALOG.json').read_text())
    checked_models=set()
    for stage in definition['stages']:
        if not stage.get('server_profile'):continue
        profile=json.loads(Path(c.input(stage['server_profile'])).read_text())
        if c.runtime.canonical_sha256(profile) not in c.lock['scientific_invariants']['allowed_server_profile_sha256']:raise ValueError('Profile not in exact experiment lock')
        model=next((m for m in c.lock['models'] if Path(m['path']).resolve()==Path(profile['model_path']).resolve()),None)
        if not model:raise ValueError('Managed profile checkpoint is not locked')
        if model['path'] not in checked_models:
            if c.runtime.sha256_file(model['path'])!=model['sha256']:raise RuntimeError('Managed checkpoint bytes changed')
            checked_models.add(model['path'])
    stages={stage['stage_id']:stage for stage in definition['stages']}
    def argument(item):
        if isinstance(item,str):return item
        if set(item)=={'input'}:return c.input(item['input'])
        if set(item)=={'config'}:
            value=c.config[item['config']]
            if not isinstance(value,(str,int,float,bool)):raise ValueError('Config argv value must be scalar')
            return str(value)
        if set(item)=={'asset'}:return str(c.runtime.contained(c.home/'src/assets',item['asset']))
        if set(item)=={'run_id'} and item['run_id'] is True:return c.run_id
        if set(item)<= {'output','path'} and 'output' in item:
            stage=stages[item['output']];path=c.output(stage['provider_repo'],stage['stage_id'])
            return str(c.runtime.contained(path,item['path'])) if 'path' in item else str(path)
        if set(item)=={'source_component','path'}:
            entry=catalog['components'][item['source_component']]
            if item['source_component'] not in definition['component_dependencies']:raise ValueError('Undeclared component argument')
            rel=c.runtime.relative_path(item['path'])
            if not any(rel==Path(root) or rel.is_relative_to(Path(root)) for root in entry['paths']):raise ValueError('Source argument outside locked component')
            return str(c.source(entry['repo_id'])/rel)
        raise ValueError('Unsupported typed argv binding: '+repr(item))
    result=[]
    for stage in definition['stages']:
        entrypoint=stage['entrypoint']
        if 'component' in entrypoint:
            entry=catalog['components'][entrypoint['component']]
            command=c.command(entry['repo_id'],entrypoint['path'])
        else:
            command=[sys.executable,str(c.repo/'components/scaffolding/v1/launch_engine.py'),'--engine',str(c.home/'src'/c.runtime.relative_path(entrypoint['engine'])),
                     '--output-root',str(c.output(stage['provider_repo'],stage['stage_id'])),'--output-contracts',json.dumps(stage['outputs'])]
            paths=set()
            for key in definition['component_dependencies']:
                entry=catalog['components'][key]
                for relative in entry['python_paths']:paths.add(str(c.source(entry['repo_id'])/relative))
            for path in sorted(paths):command+=['--provider-path',path]
            command+=['--']
        command+=[argument(item) for item in stage['arguments']]
        job=dict(stage_id=stage['stage_id'],provider_repo=stage['provider_repo'],command=command)
        if stage.get('server_profile'):job['server_profile']=stage['server_profile']
        result.append(job)
    return result
