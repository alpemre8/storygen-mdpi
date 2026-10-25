#!/usr/bin/env python3
"""Check rehydrated historical inputs. No downloading, mutation or inference."""
from pathlib import Path
import argparse, hashlib, json

HERE=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True,help='Rehydrated external depot root')
    parser.add_argument('--code-root',type=Path,default=HERE/'code')
    args=parser.parse_args()
    rows=json.loads((HERE/'provenance/RESTRICTED_INPUTS.json').read_text())['files']
    missing,changed,verified=[],[],0
    for row in rows:
        base=(args.root if row['root']=='depot' else args.code_root).resolve()
        path=(base/row['path']).resolve()
        if not path.is_relative_to(base):raise ValueError('Input path escapes root')
        if not path.is_file():missing.append({'root':row['root'],'path':row['path']});continue
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        if digest!=row['sha256']:changed.append({'root':row['root'],'path':row['path']})
        else:verified+=1
    print(json.dumps(dict(status='PASS' if not missing and not changed else 'MISSING_OR_CHANGED_INPUTS',verified=verified,missing_count=len(missing),changed_count=len(changed),missing=missing,changed=changed),indent=2))
    raise SystemExit(0 if not missing and not changed else 1)

if __name__=='__main__':main()
