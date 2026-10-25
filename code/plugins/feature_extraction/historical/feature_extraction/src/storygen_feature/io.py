from __future__ import annotations
import hashlib, json, re
from pathlib import Path
from typing import Any


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, payload: Any) -> None:
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_jsonl(path: str | Path, payload: Any) -> None:
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f: f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def sha256_json(payload: Any) -> str:
    return sha256_bytes(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode())


def normalize_scene_id(value: Any, fallback_index: int) -> str:
    if isinstance(value, str):
        s=value.strip(); m=re.search(r"(\d+)$", s)
        if s.startswith("scene_") and m: return f"scene_{int(m.group(1)):03d}"
        if s.isdigit(): return f"scene_{int(s):03d}"
        if s: return s
    if isinstance(value, int): return f"scene_{value+1:03d}"
    return f"scene_{fallback_index:03d}"


def load_script(path: str | Path) -> tuple[Any, list[dict[str, Any]]]:
    raw=read_json(path)
    scenes=raw.get("scenes") if isinstance(raw, dict) else raw
    if not isinstance(scenes, list): raise ValueError(f"Unsupported screenplay shape: {path}")
    out=[]
    for i,item in enumerate(scenes,1):
        if not isinstance(item,dict): raise ValueError(f"Scene {i} is not an object")
        scene_id=normalize_scene_id(item.get("scene_id", item.get("_id", item.get("id"))), i)
        title=str(item.get("scene_heading") or item.get("title") or item.get("heading") or "").strip()
        text=str(item.get("text") or item.get("content") or item.get("body") or "").strip()
        if not text: raise ValueError(f"Empty scene text: {scene_id}")
        out.append({"scene_id":scene_id,"scene_index":i,"title":title,"text":text,"source":item})
    return raw,out


def materialize_rewritten_script(original_raw: Any, original_scenes: list[dict[str,Any]], rewritten: list[dict[str,Any]]) -> Any:
    by_id={str(x.get("scene_id")):x for x in rewritten if isinstance(x,dict)}
    new=[]
    for scene in original_scenes:
        item=dict(scene["source"]); rep=by_id.get(scene["scene_id"])
        if rep:
            title=str(rep.get("title") or "").strip(); content=str(rep.get("content") or "").strip()
            if "scene_heading" in item: item["scene_heading"]=title
            elif "title" in item: item["title"]=title
            else: item["title"]=title
            if "text" in item: item["text"]=content
            elif "content" in item: item["content"]=content
            else: item["content"]=content
        new.append(item)
    if isinstance(original_raw,dict):
        result=dict(original_raw); result["scenes"]=new; return result
    return new
