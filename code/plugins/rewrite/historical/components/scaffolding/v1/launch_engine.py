"""Execute an owned experimental engine with explicit pinned public package paths."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--engine',type=Path,required=True)
    p.add_argument('--output-root',type=Path,required=True);p.add_argument('--output-contracts',required=True)
    p.add_argument('--provider-path',type=Path,action='append',default=[]);p.add_argument('arguments',nargs=argparse.REMAINDER)
    a=p.parse_args(argv);env={k:v for k,v in os.environ.items() if k not in {'PYTHONPATH','PYTHONHOME'}}
    env['PYTHONPATH']=os.pathsep.join(str(path.resolve()) for path in a.provider_path);env['PYTHONDONTWRITEBYTECODE']='1'
    args=a.arguments[1:] if a.arguments[:1]==['--'] else a.arguments
    result=subprocess.run([sys.executable,str(a.engine),*args],env=env)
    if result.returncode:return result.returncode
    from jsonschema import Draft202012Validator
    for contract in json.loads(a.output_contracts):
        relative=Path(contract['relative_path'])
        if relative.is_absolute() or '..' in relative.parts:raise ValueError('Output contract escapes owned stage')
        path=a.output_root/relative
        if path.is_symlink() or not path.resolve().is_relative_to(a.output_root.resolve()):raise ValueError('Output contract path is unsafe')
        Draft202012Validator(contract['schema']).validate(json.loads(path.read_text()))
    return 0

if __name__=='__main__':raise SystemExit(main())
