"""Research discovery v2: global ownership, honest readiness and purpose-separated runs."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import yaml

ROOT=Path(__file__).resolve().parents[3]
def load(path,name):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
base=load(ROOT/'components/architecture/v1/registry.py','registry_v1_dependency')
creator=load(ROOT/'components/scaffolding/v1/creator.py','scaffold_registry_dependency')


def load_registry(repo,workspace):
 roots=creator.repositories(Path(repo),workspace);creator.global_owners(roots)
 rows=base.load_registry(Path(repo))
 for row in rows:
  counts={purpose:{} for purpose in ['RESEARCH','MIGRATION_VERIFICATION','SYNTHETIC_TEST']}
  if row['registry_status']=='PACKAGED':
   runs=Path(workspace)/(row['owner_repo']+'-depot')/'experiments'/row['group_id']/row['experiment_id']/'runs'
   for root in sorted(runs.glob('*')):
    manifest=root/'run_manifest.json'
    if manifest.is_file():
     value=yaml.safe_load(manifest.read_text());purpose=value['purpose'];status=value['execution_status']
     if value['owner_repo']!=row['owner_repo'] or value['experiment_id']!=row['experiment_id']:raise ValueError('Catalog owner/run mismatch')
     if not (root/'SEALED.json').is_file():status='UNSEALED_TERMINAL'
     else:
      seal=json.loads((root/'SEALED.json').read_text())
      if creator.rt.sha256_file(manifest)!=seal['manifest_sha256']:raise RuntimeError('Catalog refuses changed sealed manifest')
     counts[purpose][status]=counts[purpose].get(status,0)+1
    elif (root/'RUN_STARTED.json').is_file():
     started=json.loads((root/'RUN_STARTED.json').read_text());purpose=started['purpose'];counts[purpose]['INCOMPLETE']=counts[purpose].get('INCOMPLETE',0)+1
  row['run_counts']=counts
  row['historical_access']='Exact physical legacy locators in '+row['owner_repo']+'-depot/catalogs/experiment_architecture_v1/legacy.jsonl'
  row['readiness']='EXACT_INPUT_BINDINGS_REQUIRED' if row['registry_status']=='PACKAGED' else 'HISTORICAL_PACKAGING_PENDING'
 return rows


def show(repo,key,workspace):
 for row in load_registry(repo,workspace):
  if row['experiment_id']==key:return row
 raise ValueError('Unknown local primary experiment: '+key)


def packaging_errors(repo,row):
 errors=[]
 if row['registry_status']!='PACKAGED':return ['Primary packaging pending']
 runner=Path(repo)/row['public_runner'];lock_path=runner.parent/'dependencies.lock.yaml'
 if not runner.is_file():errors.append('Missing matching primary runner')
 if not lock_path.is_file():errors.append('Missing exact dependency lock')
 else:
  lock=creator.contracts.validate('dependency_lock',yaml.safe_load(lock_path.read_text()))
  if lock['experiment_id']!=row['experiment_id']:errors.append('Wrong lock identity')
  for asset in lock['assets']:
   if asset['root_id']=='owner':
    path=Path(repo)/asset['path']
    if not path.is_file() or creator.rt.sha256_file(path)!=asset['sha256']:errors.append('Changed/missing locked owner asset: '+asset['path'])
 return errors


def runtime_blockers(row,config):
 if not config:return []
 bound=json.loads(Path(config).read_text());blockers=[]
 for role in ['profile','server_manifest','rewrite_server_manifest','measurement_server_manifest']:
  ref=bound.get('inputs',{}).get(role)
  if not ref:continue
  path=Path(ref['path']).expanduser()
  if not path.is_file():continue  # The exact owner preflight reports missing bindings.
  value=yaml.safe_load(path.read_text());model=value.get('model',{}) if isinstance(value,dict) else {}
  if isinstance(model,dict) and str(model.get('binding_status','')).startswith('UNBOUND'):
   blockers.append('The exact profile still declares an unbound checkpoint; create a verified new binding first')
  if row['experiment_id']=='e01_independent_extractor' and not (bound.get('technical_runtime_version','v1')=='v2' and bound.get('manage_servers',False)) and isinstance(model,dict) and model.get('tokenizer_chat_template_sha256')=='sha256:e16746b40344d6c5b5265988e0328a0bf7277be86f1c335156eae07e29c82826':
   blockers.append('Frozen E01 v1 has the verified known LF hash-format bug on this profile; explicitly select technical_runtime_version=v2 with manage_servers=true. v1 remains available through its frozen primary runner for reproduction.')
 return blockers


def doctor(repo,key,workspace,*,config=None,run_id='doctor_only',cache=None):
 rows=[show(repo,key,workspace)] if key else load_registry(repo,workspace);checks=[]
 for row in rows:
  errors=packaging_errors(repo,row)
  record=dict(experiment_id=row['experiment_id'],packaging_status='PASS' if not errors else 'FAILED',runnable=False,
              status='HUMAN_OR_RUNTIME_BLOCKED' if not errors else 'FAILED',errors=errors,detail='Exact config/model/runtime bindings and a fresh run ID are required; packaging alone does not prove readiness')
  if config and not errors:
   if len(rows)!=1:raise ValueError('A bound doctor selects exactly one experiment')
   command=[sys.executable,str(Path(repo)/row['public_runner']),'doctor','--config',str(config),'--run-id',run_id,'--workspace',str(workspace)]
   if cache:command+=['--provider-cache',str(cache)]
   result=subprocess.run(command,capture_output=True,text=True)
   record['runtime']=json.loads(result.stdout);record['status']=record['runtime']['status'];record['runnable']=result.returncode==0 and record['status']=='PLAN_READY'
   blockers=runtime_blockers(row,config)
   if blockers:record.update(status='HUMAN_OR_RUNTIME_BLOCKED',runnable=False,detail='; '.join(blockers))
  checks.append(record)
 return dict(repository=base.repo_id(Path(repo)),ready=bool(checks) and all(r['runnable'] for r in checks),experiments=checks)


def render_catalog(repo,workspace):
 rows=load_registry(repo,workspace);lines=['# Experiments','','Generated from owner manifests, exact locks and sealed run metadata. Migration verification and synthetic runs are separate from research results.','']
 for group in dict.fromkeys(row['group_id'] for row in rows):
  lines+=['## '+base.GROUPS.get(group,group),'']
  for row in [r for r in rows if r['group_id']==group]:
   key=row['experiment_id']
   if row['registry_status']=='PACKAGED':
    home=Path(row['public_runner']).parent
    counts=row['run_counts'];verification=counts['MIGRATION_VERIFICATION'];research=counts['RESEARCH']
    label=', '.join(f'{n} {status.lower()}' for status,n in sorted(verification.items())) or 'none'
    synthetic=counts['SYNTHETIC_TEST'];slabel=' Synthetic: '+', '.join(f'{n} {status.lower()}' for status,n in sorted(synthetic.items()))+'.' if synthetic else ''
    rlabel=', '.join(f'{n} {status.lower()}' for status,n in sorted(research.items())) or 'none in new namespace'
    lines.append(f"- [{key}]({row['public_runner']}) — {row['scientific_question']} [Protocol/docs]({home}/README.md) · [exact locks]({home}/dependencies.lock.yaml). Owner: `{row['owner_repo']}`. Stages: {' → '.join(stage['stage_id'] for stage in row['stages'])}. Research runs: {rlabel}. Migration verification: {label}.{slabel} Scientific validity: **{row['scientific_validity']}**.")
   else:lines.append(f"- {key} — {row.get('question','Historical protocol')}. Registered history; packaging pending.")
  lines.append('')
 lines+=['Historical results stay in their original depots; exact read-only locators live in `catalogs/experiment_architecture_v1/legacy.jsonl`. A completed migration smoke is not a paper result.','',
 'Use `python tools/experiments.py list`, `show ID`, `doctor ID`, or the owner `plan/preflight/run/status` commands. Bound doctor requires `--config` and a fresh `--run-id`.','',
 'Create an independent experiment with `python tools/new_experiment.py --spec SPEC.json`. Compatible frozen stages are selected by exact version; only the studied behavior belongs in a new owned engine. See [creation guide](docs/architecture/EXPERIMENT_CREATION_GUIDE.md).','']
 return '\n'.join(lines)


def write_catalog(repo,workspace):
 import fcntl,os,tempfile
 directory=Path(workspace)/'.storygen-architecture-locks';directory.mkdir(parents=True,exist_ok=True)
 lock=creator.rt.contained(directory,'catalog-'+base.repo_id(Path(repo))+'.lock')
 with lock.open('a+b') as stream:
  fcntl.flock(stream.fileno(),fcntl.LOCK_EX)
  try:
   text=render_catalog(repo,workspace);path=Path(repo)/'EXPERIMENTS.md'
   fd,name=tempfile.mkstemp(prefix='.catalog-',dir=Path(repo))
   try:
    with os.fdopen(fd,'w') as out:out.write(text);out.flush();os.fsync(out.fileno())
    os.replace(name,path)
   finally:
    if Path(name).exists():Path(name).unlink()
   return path
  finally:fcntl.flock(stream.fileno(),fcntl.LOCK_UN)


def main(argv=None,default_repo=ROOT):
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--repo',type=Path,default=default_repo);p.add_argument('--workspace',type=Path,default=Path.home()/'projects')
 sub=p.add_subparsers(dest='action',required=True);sub.add_parser('list');s=sub.add_parser('show');s.add_argument('experiment_id')
 s=sub.add_parser('catalog');s.add_argument('--check',action='store_true')
 s=sub.add_parser('doctor');s.add_argument('experiment_id',nargs='?');s.add_argument('--config',type=Path);s.add_argument('--run-id',default='doctor_only');s.add_argument('--provider-cache',type=Path)
 for action in ['plan','preflight','run','status']:
  s=sub.add_parser(action);s.add_argument('experiment_id');s.add_argument('--config',type=Path);s.add_argument('--run-id',default='plan_only');s.add_argument('--provider-cache',type=Path)
 a=p.parse_args(argv);repo=a.repo.resolve()
 if a.action=='list':result=load_registry(repo,a.workspace)
 elif a.action=='show':result=show(repo,a.experiment_id,a.workspace)
 elif a.action=='doctor':
  result=doctor(repo,a.experiment_id,a.workspace,config=a.config,run_id=a.run_id,cache=a.provider_cache);print(json.dumps(result,indent=2));return 0 if result['ready'] else 2
 elif a.action=='catalog':
  text=render_catalog(repo,a.workspace);path=repo/'EXPERIMENTS.md'
  if a.check:
   if not path.is_file() or path.read_text()!=text:raise ValueError('Catalog is stale')
  else:write_catalog(repo,a.workspace)
  result=dict(catalog=str(path),sha256='sha256:'+hashlib.sha256(text.encode()).hexdigest())
 else:
  row=show(repo,a.experiment_id,a.workspace)
  blockers=runtime_blockers(row,a.config) if a.action!='status' else []
  if blockers:
   print(json.dumps(dict(status='HUMAN_OR_RUNTIME_BLOCKED',reasons=blockers),indent=2));return 2
  command=[sys.executable,str(repo/row['public_runner']),a.action,'--run-id',a.run_id,'--workspace',str(a.workspace)]
  if a.config:command+=['--config',str(a.config)]
  if a.provider_cache:command+=['--provider-cache',str(a.provider_cache)]
  return subprocess.run(command).returncode
 print(json.dumps(result,indent=2));return 0

if __name__=='__main__':raise SystemExit(main())
