#!/usr/bin/env python3
"""Check the exported scope and common accidental publication hazards."""
from pathlib import Path
import csv, gzip, json, re

ROOT=Path(__file__).resolve().parents[1]
SECRET=re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|sk-[A-Za-z0-9]{32,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----\r?\n[A-Za-z0-9+/])')
TEXT_KEYS={'text','content','body','title','subtitle','scene_title','scene_heading','scene_text','source_text','rewritten_text','original_text','dialogue','dialogues','synopsis','summary','change_summary','user_instruction','system_instruction','response_text','raw_response','raw_response_text','messages','prompt','rendered_prompt'}
LOCAL_ONLY={'.git','.venv','__pycache__','.pytest_cache','.ruff_cache','reproduced','local-inputs','external-inputs'}

def narrative_fields(obj,location):
    if isinstance(obj,dict):
        for key,value in obj.items():
            if key.lower() in TEXT_KEYS and isinstance(value,(str,list,dict)) and value:
                raise ValueError('Unexpected narrative field: '+location+'/'+key)
            narrative_fields(value,location+'/'+key)
    elif isinstance(obj,list):
        for i,value in enumerate(obj):narrative_fields(value,location+'/'+str(i))

def main():
    scope=json.loads((ROOT/'release-scope.json').read_text())
    files=0;data_files=0
    for path in ROOT.rglob('*'):
        rel=path.relative_to(ROOT)
        if any(p in LOCAL_ONLY for p in rel.parts):continue
        if path.is_symlink():raise ValueError('Unexpected symlink: '+str(rel))
        if not path.is_file():continue
        files+=1
        if rel.parts[0]=='human-evaluation' and path.stem=='TasksetV5_Booklet_EN_blinded':raise ValueError('Screenplay booklet must remain local: '+str(rel))
        if path.suffix in {'.gguf','.safetensors','.pt','.pth'}:raise ValueError('Unexpected model file: '+str(rel))
        raw=path.read_bytes()
        if SECRET.search(raw):raise ValueError('Credential-shaped string in '+str(rel))
        if any(p in scope['excluded_experiments'] for p in rel.parts):raise ValueError('Excluded experiment file: '+str(rel))
        if any('naturalness' in p.lower() or 'gsrn' in p.lower() or p.lower().startswith('e07') for p in rel.parts):raise ValueError('Out-of-scope family: '+str(rel))
        if rel.parts[0] in {'data','provenance'} and path.suffix in {'.json','.jsonl','.gz'}:
            if path.suffix=='.gz':raw=gzip.decompress(raw)
            obj=[json.loads(line) for line in raw.splitlines() if line.strip()] if path.suffix=='.jsonl' else json.loads(raw)
            narrative_fields(obj,str(rel));data_files+=1
        elif rel.parts[0]=='data' and path.suffix=='.csv':
            with path.open(newline='') as stream:
                for index,row in enumerate(csv.DictReader(stream)):narrative_fields(row,str(rel)+'/'+str(index))
            data_files+=1
    print(json.dumps(dict(status='PASS',files_scanned=files,data_documents_scanned=data_files,checks=['excluded experiment directories','model binaries','credential-shaped strings','nonempty narrative fields in data/provenance JSON and data CSV','excluded screenplay booklet','symlinks'],limitation='Automated checks supplement the curated export; they are not a general copyright or privacy certification. Generic code/prompt templates and synthetic fixtures are retained.'),indent=2))

if __name__=='__main__':main()
