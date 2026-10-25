"""Own the exact E01 server while executing the unchanged independent qualifier."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time

import httpx
import yaml

ROOT=Path(__file__).resolve().parents[4]
spec=importlib.util.spec_from_file_location('e01_owned_runtime_v1',ROOT/'components/runtime/v1/runtime.py')
runtime=importlib.util.module_from_spec(spec);spec.loader.exec_module(runtime)


def run(args):
    cli=args.provider_root/'feature_extraction/cli/qualify_independent_extractor.py'
    profile=yaml.safe_load(args.profile.read_text())
    host,port=profile['runtime']['host'],profile['runtime']['port']
    if host!='127.0.0.1' or port!=8081:raise ValueError('Exact local E01 endpoint required')
    command=shlex.split(subprocess.check_output([sys.executable,str(cli),'server-command','--profile',str(args.profile)],text=True))
    env={k:v for k,v in os.environ.items() if not k.startswith('LLAMA_ARG_')}
    env['LD_LIBRARY_PATH']=str(Path(command[0]).parent)
    # OwnedProcess refuses occupied ports and only stops its own Popen child.
    with runtime.OwnedProcess(command,args.server_log,env=env,port=port) as process:
        deadline=time.monotonic()+120
        while True:
            if process.process.poll() is not None:raise RuntimeError('Exact E01 server exited before readiness')
            try:
                health=httpx.get(f'http://{host}:{port}/health',timeout=1)
                if health.status_code==200:break
            except httpx.TransportError:pass
            if time.monotonic()>deadline:raise TimeoutError('Exact E01 server startup exceeded 120 seconds')
            time.sleep(0.25)
        # The scientific CLI checks full /proc argv/executable/env, template, slots,
        # context, checkpoint precision/hash and profile bytes before any inference.
        subprocess.run([sys.executable,str(cli),'smoke','--profile',str(args.profile),
            '--input-contract',str(args.input_contract),'--selection',str(args.selection),
            '--output-dir',str(args.output),'--execute-inference'],check=True)
    return 0


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['provider-root','profile','input-contract','selection','output','server-log']:
        p.add_argument('--'+name,type=Path,required=True)
    return run(p.parse_args(argv))

if __name__=='__main__':raise SystemExit(main())
