"""Exact baseline technical API; scientific construction remains in provider APIs."""
from pathlib import Path
import hashlib,json,os,subprocess
from .bindings import git

def live_runtime(config, key):
    import httpx
    server = config[key+'_server']; url = server['base_url'].removesuffix('/v1')
    record = read(Path(config['roots']['rewrite'])/'runtime'/('SERVER_'+key.upper()+'.json'))
    cmdline = Path('/proc')/str(record['pid'])/'cmdline'
    if cmdline.read_bytes().rstrip(b'\0').split(b'\0') != [s.encode() for s in server_command(server)]:
        raise RuntimeError('Author server process command differs from frozen profile')
    if (cmdline.parent/'exe').resolve() != Path(server['server_binary']).resolve():
        raise RuntimeError('Author server binary differs from frozen identity')
    response = httpx.get(url+'/props',timeout=30); response.raise_for_status(); props=response.json()
    if props['model_alias'] != server['model_alias'] or Path(props['model_path']).resolve() != Path(server['model_path']).resolve():
        raise RuntimeError('Live checkpoint identity mismatch')
    if props['total_slots'] != server['parallel_slots'] or props['default_generation_settings']['n_ctx'] != server['context_per_slot']:
        raise RuntimeError('Live server slot/context mismatch')
    write(Path(config['roots']['rewrite'])/'runtime'/('LIVE_'+key.upper()+'.json'),props)
    return url

def write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n')

def server_command(server):
    command = [server['server_binary'],'--offline','-m',server['model_path'],'--alias',server['model_alias'],
            '--host','127.0.0.1','--port','8080','--device',server['device'],'--fit','off',
            '--parallel',str(server['parallel_slots']),'--ctx-size',str(server['total_context']),
            '--batch-size',str(server['batch_size']),'--ubatch-size',str(server['ubatch_size']),
            '--no-kv-unified','--cont-batching','--flash-attn','on','--cache-type-k','f16','--cache-type-v','f16',
            '--timeout',str(server['timeout_seconds'])]
    for key,flag in [('threads','--threads'),('threads_batch','--threads-batch'),('threads_http','--threads-http')]:
        if key in server: command += [flag,str(server[key])]
    return command

def context_check(url, payloads, output_tokens, context):
    """Author-run tokenizer check; no completion request, no scientific measurement."""
    import httpx
    with httpx.Client(timeout=60) as client:
        for index,payload in enumerate(payloads,1):
            applied=client.post(url+'/apply-template',json=payload)
            applied.raise_for_status()
            tokenized=client.post(url+'/tokenize',json={'content':applied.json()['prompt'],'add_special':False,'parse_special':True})
            tokenized.raise_for_status(); count=len(tokenized.json()['tokens'])
            if count+output_tokens>context:
                raise RuntimeError(f'Complete primary request {index} exceeds frozen context; STOP without changing protocol')
    print(f'Context capacity verified for {index if payloads else 0} complete primary requests')

def read(path):
    return json.loads(Path(path).read_text())

def checked(ref):
    if sha(ref['path']) != ref['sha256']:
        raise RuntimeError('Frozen SHA mismatch: ' + str(ref['path']))
    return read(ref['path'])

def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b''):
            digest.update(block)
    return 'sha256:' + digest.hexdigest()
