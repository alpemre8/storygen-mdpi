"""Reuse the exact frozen E01 API with an explicit versioned technical comparator."""
import argparse
import importlib.util
import json
from pathlib import Path

import storygen_feature.independent as scientific

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('e01_template_identity_v2',HERE/'template_identity.py')
identity=importlib.util.module_from_spec(spec);spec.loader.exec_module(identity)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['provider-root','profile','input-contract','selection','output-dir']:p.add_argument('--'+name,type=Path,required=True)
    args=p.parse_args();provider=args.provider_root.resolve()
    if not Path(scientific.__file__).resolve().is_relative_to(provider/'feature_extraction/src'):
        raise RuntimeError('Frozen independent API must come from the pinned provider')
    original=scientific._verify_chat_template
    # Only this technical helper changes; run_smoke, strict scorer, profile,
    # precision, /proc/API, sampling, schema, retries and failure gates stay frozen.
    scientific._verify_chat_template=identity.compare
    try:
        result=scientific.run_smoke(core=provider/'measurement',profile=args.profile,
            input_contract=args.input_contract,selection_path=args.selection,output=args.output_dir,
            dry_run=False,execute_inference=True,resume=False)
        print(json.dumps(result,indent=2));return 0
    finally:
        scientific._verify_chat_template=original
        if args.output_dir.exists():
            record=dict(component_id=identity.ID,component_sha256=identity.digest((HERE/'template_identity.py').read_bytes()),
                frozen_api_path=str(Path(scientific.__file__).resolve()),frozen_api_sha256=identity.digest(Path(scientific.__file__).read_bytes()),
                policy='Only the originally declared exact known trailing-LF exception; digest representation normalized; no arbitrary template edits accepted')
            with (args.output_dir/'technical_runtime_comparator.json').open('x') as out:json.dump(record,out,indent=2);out.write('\n')

if __name__=='__main__':raise SystemExit(main())
