"""Architecture contracts v1.0. Legacy scientific validators are unchanged."""
from pathlib import Path
import re
import json
from jsonschema import Draft202012Validator

ROOT=Path(__file__).resolve().parent

def validate(kind,value):
    schema=json.loads((ROOT/(kind+'.schema.json')).read_text())
    Draft202012Validator(schema).validate(value)
    if kind=='experiment':
        expected=f"experiments/{value['group_id']}/{value['experiment_id']}/{value['experiment_id']}.py"
        if value['public_runner']!=expected:raise ValueError('Runner must match owner directory: '+expected)
        ids=[s['stage_id'] for s in value['stages']]
        if len(ids)!=len(set(ids)):raise ValueError('Duplicate stage ID')
        seen=set()
        for stage in value['stages']:
            if not set(stage['depends_on'])<=seen:raise ValueError('Stages must be a topologically ordered DAG')
            seen.add(stage['stage_id'])
        if value['scientific_validity']=='VALIDATED':
            raise ValueError('v1 migration manifests cannot assert scientific validation without a separate evidence contract')
    if kind=='dependency_lock':
        repos=[r['repo_id'] for r in value['source_repositories']]
        if len(repos)!=len(set(repos)):raise ValueError('Duplicate locked repository')
        components=[c['component_id'] for c in value['components']]
        if len(components)!=len(set(components)):raise ValueError('Duplicate locked component')
        for c in value['components']:
            if c['repo_id'] not in repos:raise ValueError('Component has no exact source lock')
            for p in c['paths']:safe_relative(p)
    if kind=='artifact_ref':safe_relative(value['locator']['relative_path'])
    return value

def safe_relative(value):
    p=Path(value)
    if not value or p.is_absolute() or '..' in p.parts or '\\' in value or value in ('.',''):
        raise ValueError('Unsafe relative path: '+value)
    return p

def validate_owners(owners):
    seen=set()
    for row in owners:
        key=row['experiment_id']
        if key in seen:raise ValueError('Duplicate experiment owner: '+key)
        seen.add(key)
        if not re.fullmatch(r'[a-z][a-z0-9_]*',key):raise ValueError('Invalid experiment ID')
    return owners
