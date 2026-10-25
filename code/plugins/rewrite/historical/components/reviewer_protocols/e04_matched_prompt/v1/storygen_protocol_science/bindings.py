"""Exact provider locations supplied by the versioned subprocess launcher."""
import importlib
import os
from pathlib import Path
import subprocess

WORKSPACE=Path(os.environ['STORYGEN_PROTOCOL_WORKSPACE']).resolve()
REWRITE=WORKSPACE/'storygen-rewrite'
BACKEND=Path(os.environ['STORYGEN_PROTOCOL_BACKEND_ROOT']).resolve()

def imports(workspace):
    expected={'storygen':WORKSPACE/'storygen-rewrite/rewrite/src',
              'storygen_feature':WORKSPACE/'storygen-feature-extraction/feature_extraction/src',
              'storygen_measurement_core':WORKSPACE/'storygen-feature-extraction/measurement/src',
              'storygen_evaluation':WORKSPACE/'storygen-evaluation/evaluation/src'}
    for name,root in expected.items():
        module=importlib.import_module(name)
        if not Path(module.__file__).resolve().is_relative_to(root):
            raise RuntimeError('Scientific import escaped its exact frozen provider: '+name)

def git(repo,*args):
    repo=Path(repo)
    if repo.name=='llama.cpp':repo=BACKEND
    return subprocess.check_output(['git','-C',str(repo),*args],text=True).strip()
