"""Create an independently owned, version-locked experiment without changing old runners."""
from pathlib import Path
import importlib.util
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('experiment_creator_v1',ROOT/'components/scaffolding/v1/creator.py')
creator=importlib.util.module_from_spec(spec);spec.loader.exec_module(creator)
if __name__=='__main__':raise SystemExit(creator.main(default_repo=ROOT))
