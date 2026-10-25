from pathlib import Path
import argparse, json, random, yaml
ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent
from sys import path as syspath
syspath[:0] = [str(PROJECT), str(ROOT / "src")]
from storygen_feature.io import load_script
from tools.depot_paths import owned_output_path

p = argparse.ArgumentParser(description="Build the canonical balanced 100-scene reliability sample: 10 films x 10 scenes.")
p.add_argument("--film-set", required=True)
p.add_argument("--input-root", required=True, help="Root containing films/<film_id>/script.json")
p.add_argument("--output", required=True)
p.add_argument("--seed", type=int, default=42)
a = p.parse_args()

def r(x):
    q=Path(x); return q.resolve() if q.is_absolute() else (PROJECT/q).resolve()
film_set=yaml.safe_load(r(a.film_set).read_text()) or {}
input_root=r(a.input_root)
films=[str(x) for x in film_set.get("films",[])]
if len(films)!=10 or len(set(films))!=10: raise SystemExit("Canonical reliability sample requires exactly 10 unique films")
rows=[]
for film_id in films:
    script=input_root/"films"/film_id/"script.json"
    _,scenes=load_script(script)
    if len(scenes)<10: raise SystemExit(f"{film_id} has fewer than 10 scenes")
    rng=random.Random(f"{a.seed}:{film_id}")
    selected=sorted(rng.sample(range(len(scenes)),10))
    for i in selected: rows.append({"film_id":film_id,"scene_id":scenes[i]["scene_id"],"script_path":str(script)})
out=owned_output_path(a.output); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(rows,indent=2)+"\n")
print(json.dumps({"output":str(out),"scene_count":len(rows),"film_count":len(films),"per_film":10,"seed":a.seed},indent=2))
