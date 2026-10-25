"""Create an isolated owner experiment from explicit research metadata and a typed DAG."""
from __future__ import annotations
import argparse
import ast
import importlib.util
import importlib.metadata
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[3]
def load(path,name):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
rt=load(ROOT/'components/runtime/v1/runtime.py','scaffold_runtime_v1')
contracts=load(ROOT/'contracts/v1/validate.py','scaffold_contracts_v1')
MAIN=['storygen-rewrite','storygen-feature-extraction','storygen-evaluation']


def repositories(repo,workspace):
    result={}
    for name in MAIN:
        path=repo if json.loads((repo/'REPOSITORY_MANIFEST.json').read_text())['repository_id']==name else repo.parent/name
        if not (path/'REPOSITORY_MANIFEST.json').exists():path=Path(workspace)/name
        if json.loads((path/'REPOSITORY_MANIFEST.json').read_text())['repository_id']!=name:raise ValueError('Repository identity mismatch')
        result[name]=path.resolve()
    return result


def global_owners(roots):
    owners={};seen=set()
    for name,root in roots.items():
        for row in json.loads((root/'contracts/v1/owner_registry.json').read_text())['owners']:
            key=row['experiment_id']
            if key in owners and owners[key]!=row['owner_repo']:raise ValueError('Conflicting registered primary owner')
            owners[key]=row['owner_repo']
    for name,root in roots.items():
        for p in sorted(root.glob('experiments/*/*/experiment.yaml')):
            import yaml
            value=contracts.validate('experiment',yaml.safe_load(p.read_text()))
            key=value['experiment_id']
            if key in seen or (key in owners and owners[key]!=name):raise ValueError('Duplicate global experiment owner: '+key)
            if value['owner_repo']!=name:raise ValueError('Wrong primary repository owner')
            owners[key]=name
            seen.add(key)
    return owners


def check_engine(source):
    tree=ast.parse(source)
    for node in ast.walk(tree):
        names=[]
        if isinstance(node,ast.Import):names=[alias.name for alias in node.names]
        if isinstance(node,ast.ImportFrom):names=[node.module or '']
        if any(name=='experiments' or name.startswith(('experiments.','tools.e0')) for name in names):
            raise ValueError('Direct private experiment imports forbidden; select a versioned component')
        if isinstance(node,ast.Attribute) and isinstance(node.value,ast.Name) and node.value.id=='sys' and node.attr=='path':
            raise ValueError('Mutable sys.path is forbidden; use pinned public package paths')


def validate_definition(spec,catalog):
    required={'owner_repo','group_id','slug','scientific_question','hypothesis','independent_variables','experimental_variants','control_components','sample_population','unit_of_analysis','inputs','requested_outputs','component_dependencies','stages','research_limitations','protocol_id'}
    missing=required-set(spec)
    if missing:raise ValueError('Missing explicit research fields: '+repr(sorted(missing)))
    if spec['owner_repo'] not in MAIN:raise ValueError('Main-repo scaffold supports the three main owners; Naturalness retains its independent workflow')
    for key in ['group_id','slug']:
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,79}',spec[key]):raise ValueError('Invalid '+key)
    selected={}
    for key in spec['component_dependencies']:
        if key not in catalog['components']:raise ValueError('Unknown/unpinned component: '+key)
        selected[key]=catalog['components'][key]
    pending=list(selected)
    while pending:
        for key in selected[pending.pop()].get('dependencies',[]):
            if key not in selected:selected[key]=catalog['components'][key];pending.append(key)
    if not selected:raise ValueError('At least one explicit compatible frozen control component required')
    if not spec['experimental_variants'] or any(not isinstance(value,str) or not value for value in spec['experimental_variants']):raise ValueError('Explicit experimental variants required')
    if not set(spec['component_dependencies'])<=set(spec['control_components']):raise ValueError('All selected component versions must be explicit controls')
    names=[item['name'] for item in spec['inputs']]
    if len(names)!=len(set(names)) or any(not re.fullmatch(r'[a-z][a-z0-9_]*',name) for name in names):raise ValueError('Unique explicit input names required')
    available={item['contract'] for item in spec['inputs']};seen={};ancestors={};stages=[]
    for stage in spec['stages']:
        key=stage['stage_id']
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,79}',key) or key in seen:raise ValueError('Invalid/duplicate stage ID')
        if any(value in stage['arguments'] for value in ['--overwrite','--overwrite-stale','--resume','--retry-failed-only']):raise ValueError('Fresh runs cannot overwrite or resume old outputs')
        dependencies=stage['depends_on']
        if not set(dependencies)<=set(seen):raise ValueError('Stages must form an explicit ordered DAG')
        parents=set(dependencies)
        for parent in dependencies:parents.update(ancestors[parent])
        for argument in stage['arguments']:
            if isinstance(argument,str) and Path(argument).is_absolute():raise ValueError('Absolute data paths belong in exact input/config bindings, not pipeline argv literals')
            if isinstance(argument,dict):
                if 'output' in argument and argument['output'] not in parents|{key}:raise ValueError('Output argument has no declared upstream DAG edge')
                if 'input' in argument and argument['input'] not in names:raise ValueError('Undeclared exact input argument')
        upstream=set(available)
        for parent in dependencies:upstream.update(seen[parent])
        entry=stage['entrypoint']
        if set(entry)=={'component','path'}:
            if entry['component'] not in selected:raise ValueError('Stage component must be explicitly selected')
            component=selected[entry['component']]
            if entry['path'] not in component['interfaces']:raise ValueError('Only public compatible component entrypoints are permitted')
            if stage['provider_repo']!=component['repo_id']:raise ValueError('Component provider identity mismatch')
            interface=component['interfaces'][entry['path']]
            required_contracts=set(interface['requires']);provides=set(interface['provides'])
        elif set(entry)=={'engine'}:
            rt.relative_path(entry['engine'])
            if entry['engine'] not in spec.get('engine_sources',{}):raise ValueError('Owned experimental engine source required')
            if stage['provider_repo']!=spec['owner_repo']:raise ValueError('Owned experimental code must identify its primary source owner')
            required_contracts=set(stage['requires']);provides=set(stage['provides'])
            if not stage.get('outputs'):raise ValueError('Experimental engines require explicit output schemas')
            for output in stage['outputs']:
                rt.relative_path(output['relative_path'])
                if output['contract'] not in provides:raise ValueError('Output contract not declared by experimental engine')
                from jsonschema import Draft202012Validator
                Draft202012Validator.check_schema(output['schema'])
        else:raise ValueError('Exactly one public component entrypoint or owned engine required')
        if not required_contracts<=upstream:raise ValueError('Incompatible/missing upstream contracts: '+repr(sorted(required_contracts-upstream)))
        seen[key]=upstream|provides;ancestors[key]=parents;stages.append(dict(stage_id=key,provider_repo=stage['provider_repo'],action=stage['action'],depends_on=dependencies))
    return selected,stages


def _create(spec,*,repo=ROOT,workspace=Path.home()/'projects'):
    roots=repositories(Path(repo).resolve(),workspace);owners=global_owners(roots)
    catalog=json.loads((Path(repo)/'components/scaffolding/v1/COMPONENT_CATALOG.json').read_text())
    selected,stages=validate_definition(spec,catalog)
    slug=spec['slug']
    if slug in owners:raise ValueError('Duplicate global experiment ID: '+slug)
    target=roots[spec['owner_repo']];home=rt.contained(target,'experiments/'+spec['group_id']+'/'+slug)
    if home.exists():raise FileExistsError('Experiment namespace already exists')
    controls=list(dict.fromkeys(spec['control_components']+list(selected)))
    manifest=dict(schema_version='1.0',experiment_id=slug,group_id=spec['group_id'],owner_repo=spec['owner_repo'],scientific_question=spec['scientific_question'],
        hypothesis=spec['hypothesis'],protocol_id=spec['protocol_id'],reference_protocol_id=spec.get('reference_protocol_id'),independent_variables=spec['independent_variables'],
        control_components=controls,sample_population=spec['sample_population'],unit_of_analysis=spec['unit_of_analysis'],stages=stages,requested_outputs=spec['requested_outputs'],
        public_runner=f"experiments/{spec['group_id']}/{slug}/{slug}.py",research_limitations=spec['research_limitations'],execution_status='NOT_RUN',contract_status='UNVERIFIED',scientific_validity='UNVERIFIED',legacy_entrypoints=[],adapter='declarative_pipeline_v1')
    contracts.validate('experiment',manifest)
    pipeline={key:spec[key] for key in ['inputs','stages','experimental_variants']};pipeline['component_dependencies']=list(selected);pipeline['synthetic_only']=bool(spec.get('synthetic_only',False))
    engines={};engine_imports=set()
    for name,source in spec.get('engine_sources',{}).items():
        relative=rt.relative_path(name)
        if relative.suffix!='.py':raise ValueError('Owned engine source must be Python')
        if isinstance(source,dict):
            p=Path(source['source_path']).resolve()
            if any('experiments' in p.relative_to(root).parts for root in roots.values() if p.is_relative_to(root)):
                raise ValueError('Do not copy another experiment private source')
            source=p.read_text()
        if not isinstance(source,str):raise ValueError('Engine source text or explicit source_path required')
        check_engine(source);engines[str(relative)]=source
        all_modules={module for entry in catalog['components'].values() for module in entry.get('python_modules',[])}
        project_roots={module.split('.')[0] for module in all_modules}
        owned_packages={Path(name).parts[0].removesuffix('.py') for name in spec.get('engine_sources',{})}
        if (project_roots|{'storygen_naturalness'})&owned_packages:raise ValueError('Owned packages cannot shadow frozen public components')
        selected_modules={module for entry in selected.values() for module in entry.get('python_modules',[])}
        imports=[];full_imports=[]
        for node in ast.walk(ast.parse(source)):
            if isinstance(node,ast.Import):full_imports += [alias.name for alias in node.names]
            if isinstance(node,ast.ImportFrom) and node.level==0:
                full_imports += [(node.module or '')+('.'+alias.name if alias.name!='*' else '') for alias in node.names]
        for name in full_imports:
            package=name.split('.')[0];imports.append(package)
            if package in project_roots:
                if not any(name==module or name.startswith(module+'.') or (name==package and module.startswith(package+'.')) for module in selected_modules):
                    raise ValueError('StoryGen package requires an explicitly pinned component: '+name)
            elif package.startswith('storygen_') and package not in owned_packages:raise ValueError('Unregistered StoryGen package needs an explicit frozen source component: '+package)
        engine_imports.update(imports)
    runner='''"""Primary owner runner; exact protocol and provider locks are local."""
from pathlib import Path
import importlib.util
ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('owner_envelope_v4',ROOT/'components/execution/v4/envelope.py')
envelope=importlib.util.module_from_spec(spec);spec.loader.exec_module(envelope)
if __name__=='__main__':raise SystemExit(envelope.owner_main(__file__,Path(__file__).parent/'src/protocol.py'))
'''
    recipe='''"""Independent experiment pipeline; only versioned public components are reused."""
from pathlib import Path
import importlib.util
import json
ROOT=Path(__file__).resolve().parents[4]
spec=importlib.util.spec_from_file_location('scaffold_pipeline_v1',ROOT/'components/scaffolding/v1/pipeline.py')
shared=importlib.util.module_from_spec(spec);spec.loader.exec_module(shared)
DEFINITION=json.loads(Path(__file__).with_name('pipeline.json').read_text())
REQUIRED_CONFIG={'purpose':'Explicit run purpose','inputs':[item['name'] for item in DEFINITION['inputs']],'pipeline':'Exact frozen compatible components or owned experimental engines'}
def plan(context):return shared.plan(context,DEFINITION)
'''
    files={slug+'.py':runner.encode(),'src/protocol.py':recipe.encode(),'src/pipeline.json':rt.json_bytes(pipeline),'experiment.yaml':rt.json_bytes(manifest)}
    files.update({'src/'+name:text.encode() for name,text in engines.items()})
    for name,value in spec.get('scientific_assets',{}).items():
        relative=rt.relative_path(name)
        if any(part in {'.git','__pycache__'} for part in relative.parts):raise ValueError('Scientific asset path is reserved')
        if isinstance(value,dict) and set(value)=={'source_path'}:
            source=Path(value['source_path']).resolve()
            if any('experiments' in source.relative_to(root).parts for root in roots.values() if source.is_relative_to(root)):raise ValueError('Reuse old experiment data by exact input reference; do not copy private assets')
            if source.stat().st_size>2*1024*1024:raise ValueError('Large scientific inputs must remain exact artifact references')
            payload=source.read_text().encode()
        else:payload=value.encode() if isinstance(value,str) else rt.json_bytes(value)
        if len(payload)>2*1024*1024:raise ValueError('Large scientific inputs must remain exact artifact references')
        files['src/assets/'+str(relative)]=payload
    input_schema=dict(type='object',required=['purpose','inputs'],properties=dict(purpose=dict(enum=['RESEARCH','MIGRATION_VERIFICATION','SYNTHETIC_TEST']),inputs=dict(type='object',required=[v['name'] for v in spec['inputs']],properties={v['name']:dict(type='object',required=['path','sha256'],properties=dict(path=dict(type='string'),sha256=dict(type='string',pattern='^sha256:[a-f0-9]{64}$')),additionalProperties=False) for v in spec['inputs']},additionalProperties=False)),additionalProperties=True)
    files['schemas/run_configuration.schema.json']=rt.json_bytes(input_schema)
    config=dict(purpose='SYNTHETIC_TEST' if pipeline['synthetic_only'] else 'MIGRATION_VERIFICATION',inputs={v['name']:dict(path='BIND_EXACT_'+v['name'],sha256='sha256:'+'0'*64) for v in spec['inputs']})
    config.update(spec.get('configuration_defaults',{}))
    if spec.get('models') and 'model_file' not in config:config['model_file']=spec['models'][0]['path']
    allowed_profiles=[]
    for name,value in spec.get('server_profiles',{}).items():
        if name not in {item['name'] for item in spec['inputs']}:raise ValueError('Server profile must be a declared input')
        path=Path(value).resolve();profile=json.loads(path.read_text());allowed_profiles.append(rt.canonical_sha256(profile))
        config['inputs'][name]=dict(path=str(path),sha256=rt.sha256_file(path))
    if any(stage.get('server_profile') for stage in spec['stages']) and not allowed_profiles:raise ValueError('Managed servers require explicit locked profiles')
    files['run.example.json']=rt.json_bytes(config)
    files['README.md']=(f"# {slug}\n\n{spec['scientific_question']}\n\nOwner: `{spec['owner_repo']}`; protocol: `{spec['protocol_id']}`. {spec['hypothesis']}\n\nUnits: {spec['unit_of_analysis']}. Population: {spec['sample_population']}.\n\nEdit only this experiment's owned engines/data. Frozen controls are selected in src/pipeline.json and dependencies.lock.yaml. New scientific behavior needs its own code/version; incompatible contracts are rejected. Owned engines import pinned public packages through a controlled subprocess environment.\n\nRun `{slug}.py plan`, then `preflight --config run.example.json --run-id ID`, `run` with the same bindings and a fresh ID, or `status --run-id ID`. Bind every input to actual immutable bytes first. Commit exact owner assets before RESEARCH. Synthetic engines accept SYNTHETIC_TEST only. All stage outputs/receipts/logs and the sole manifest/seal stay below this experiment's owner-depot root; existing experiments and old runs are never edited.\n").encode()
    files['tests/test_scaffold_contract.py']=("from pathlib import Path\nimport json\nHOME=Path(__file__).resolve().parents[1]\ndef test_owned_runner_and_exact_pipeline_exist():\n    value=json.loads((HOME/'experiment.yaml').read_text())\n    assert (HOME/(value['experiment_id']+'.py')).is_file()\n    assert json.loads((HOME/'dependencies.lock.yaml').read_text())['experiment_id']==value['experiment_id']\n    assert (HOME/'src/pipeline.json').is_file()\n").encode()
    sources={row['repo_id']:row['source'] for row in selected.values()}
    if spec['owner_repo'] not in sources:sources[spec['owner_repo']]=catalog['repositories'][spec['owner_repo']]
    components=[{key:entry[key] for key in ['component_id','version','repo_id','paths','sha256']} for entry in selected.values()]
    assets=[]
    import hashlib
    for relative,payload in files.items():
        if relative in ['README.md','run.example.json'] or relative.startswith('tests/'):continue
        assets.append(dict(role='owned_experiment_source_or_schema',root_id='owner',path=str((home/relative).relative_to(target)),sha256='sha256:'+hashlib.sha256(payload).hexdigest()))
    for folder in ['components/scaffolding/v1','components/execution/v3','components/execution/v4','components/artifacts/v1','components/artifacts/v2','components/runtime/v1','contracts/v1']:
        for p in sorted((target/folder).rglob('*')):
            if p.is_file() and p.suffix in {'.py','.json'} and '__pycache__' not in p.parts:
                assets.append(dict(role='versioned_technical_dependency',root_id='owner',path=str(p.relative_to(target)),sha256=rt.sha256_file(p)))
    runtime_profile=dict(catalog['runtime_profile'])
    if not spec.get('models'):runtime_profile['backend_files']=[]
    environment=catalog['environment'];extra_packages=dict(spec.get('environment_packages',{}))
    own_modules={Path(name).parts[0].removesuffix('.py') for name in engines}
    distribution_map=importlib.metadata.packages_distributions()
    for package in sorted(engine_imports-set(sys.stdlib_module_names)-own_modules-{''}):
        if package in {module.split('.')[0] for entry in catalog['components'].values() for module in entry.get('python_modules',[])}:continue  # Explicit frozen source component guards above.
        if package not in distribution_map:raise ValueError('Engine import needs an owned source or installed versioned dependency: '+package)
        for name in distribution_map[package]:
            distribution=importlib.metadata.distribution(name);direct=distribution.read_text('direct_url.json')
            if direct and json.loads(direct).get('dir_info',{}).get('editable'):raise ValueError('Editable external code needs an explicit frozen source component: '+name)
            extra_packages.setdefault(name,distribution.version)
    if extra_packages:
        from packaging.requirements import Requirement
        from packaging.utils import canonicalize_name
        packages=dict(environment['packages']);pending=list(extra_packages)
        for name,expected in extra_packages.items():
            if importlib.metadata.version(name)!=expected:raise ValueError('Additional package must already be installed at its exact declared version')
            if canonicalize_name(name) in packages and packages[canonicalize_name(name)]!=expected:raise ValueError('Cannot silently replace the frozen reference environment')
        seen=set()
        while pending:
            name=pending.pop();key=canonicalize_name(name)
            if key in seen:continue
            seen.add(key);distribution=importlib.metadata.distribution(name)
            if key in environment['packages'] and environment['packages'][key]!=distribution.version:raise ValueError('Transitive dependency would replace the frozen reference environment: '+name)
            packages[key]=distribution.version
            for requirement in distribution.requires or []:
                requirement=Requirement(requirement)
                if requirement.marker is None or requirement.marker.evaluate({'extra':''}):pending.append(requirement.name)
        identity=dict(python=environment['python'],packages=dict(sorted(packages.items())));environment=dict(**identity,sha256=rt.canonical_sha256(identity))
    lock=dict(schema_version='1.0',experiment_id=slug,source_repositories=list(sources.values()),components=components,assets=assets,models=spec.get('models',[]),
        runtime_profile=runtime_profile,environment=environment,scientific_invariants=dict(owner_depot_only=True,immutable_reference_components=True,synthetic_only=pipeline['synthetic_only'],allowed_server_profile_sha256=allowed_profiles,creation_spec_sha256=rt.canonical_sha256(spec)),run_binding_policy='EXACT_INPUT_MODEL_RUNTIME_HASHES_REQUIRED')
    contracts.validate('dependency_lock',lock);files['dependencies.lock.yaml']=rt.json_bytes(lock)
    home.mkdir(parents=True,exist_ok=False)
    # Publish the discoverable manifest last, after all concrete source/lock/schema files.
    for relative,payload in sorted(files.items(),key=lambda pair:pair[0]=='experiment.yaml'):
        path=rt.contained(home,relative);path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as out:out.write(payload)
    registry=load(target/'components/architecture/v2/registry.py','created_experiment_registry')
    registry.write_catalog(target,Path(workspace))
    return dict(status='CREATED',owner_repo=spec['owner_repo'],experiment_id=slug,home=str(home),runner=str(home/(slug+'.py')),lock_sha256=rt.sha256_file(home/'dependencies.lock.yaml'))


def create(spec,*,repo=ROOT,workspace=Path.home()/'projects'):
    import fcntl
    slug=spec.get('slug','')
    if not re.fullmatch(r'[a-z][a-z0-9_]{0,79}',slug):raise ValueError('Valid explicit slug required')
    directory=Path(workspace)/'.storygen-architecture-locks';directory.mkdir(parents=True,exist_ok=True)
    path=rt.contained(directory,slug+'.lock')
    with path.open('a+b') as stream:
        fcntl.flock(stream.fileno(),fcntl.LOCK_EX)
        try:return _create(spec,repo=repo,workspace=workspace)
        finally:fcntl.flock(stream.fileno(),fcntl.LOCK_UN)


def main(argv=None,default_repo=ROOT):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--spec',type=Path,required=True);p.add_argument('--repo',type=Path,default=default_repo);p.add_argument('--workspace',type=Path,default=Path.home()/'projects')
    a=p.parse_args(argv)
    try:result=create(json.loads(a.spec.read_text()),repo=a.repo,workspace=a.workspace)
    except Exception as exc:
        print(json.dumps(dict(status='REJECTED',reason=str(exc)),indent=2));return 2
    print(json.dumps(result,indent=2));return 0

if __name__=='__main__':raise SystemExit(main())
