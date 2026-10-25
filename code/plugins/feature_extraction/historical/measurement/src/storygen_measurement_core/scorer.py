from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json, math, threading
from .protocol import MeasurementProtocol
from .client import OpenAICompatibleClient
from .io import sha256_json, sha256_bytes, read_json, write_json

@dataclass(frozen=True)
class MeasurementResult:
    status:str
    features:dict[str,float]|None
    attempts:int
    response_text:str|None
    cache_key:str
    error:str|None
    provenance:dict[str,Any]
    cache_hit:bool=False

class CanonicalFeatureScorer:
    def __init__(self, protocol:MeasurementProtocol, *, client:Any|None=None, cache_path:str|Path|None=None, use_cache:bool=True):
        self.protocol=protocol; self.client=client; self.cache_path=Path(cache_path) if cache_path else None; self.use_cache=use_cache
        self.cache={}
        self._cache_lock=threading.RLock()
        self._cache_dirty=False
        if self.cache_path and self.cache_path.exists():
            loaded=read_json(self.cache_path); self.cache=loaded if isinstance(loaded,dict) else {}
    def _render(self, film_id:str, scene_id:str, title:str, text:str)->str:
        return self.protocol.prompt_text.replace("{{film_id}}",film_id).replace("{{scene_id}}",scene_id).replace("{{scene_title}}",title).replace("{{scene_text}}",text)
    def _key(self, film_id:str, scene_id:str, title:str, text:str)->str:
        model=self.protocol.model
        return sha256_json({"cache_version":"measurement-cache-v3","protocol_hash":self.protocol.protocol_hash,
          "model_file_hash":model.get("model_sha256"),"model_alias":model.get("alias"),"prompt_hash":self.protocol.prompt_hash,
          "schema_hash":self.protocol.schema_hash,"decoding_hash":self.protocol.decoding_hash,"film_id":film_id,"scene_id":scene_id,
          "scene_title":title,"scene_text_hash":sha256_bytes(text.encode())})
    def _parse(self, text:str)->dict[str,float]:
        try: obj=json.loads(text)
        except json.JSONDecodeError:
            s=text.find("{"); e=text.rfind("}")
            if s<0 or e<=s: raise ValueError("No JSON object in response")
            obj=json.loads(text[s:e+1])
        values=obj.get("features") if isinstance(obj,dict) else None
        if not isinstance(values,dict): raise ValueError("Missing features object")
        out={}; clamp=bool(self.protocol.config.get("normalization",{}).get("clamp_values",True))
        for f in self.protocol.features:
            value=values.get(f)
            if isinstance(value,bool) or value is None: raise ValueError(f"Missing/invalid feature: {f}")
            score=float(value)
            if not math.isfinite(score): raise ValueError(f"Nonfinite feature: {f}")
            if clamp: score=max(0.0,min(1.0,score))
            if not 0<=score<=1: raise ValueError(f"Out-of-range feature: {f}")
            out[f]=round(score,6)
        if set(values) != set(self.protocol.features): raise ValueError("Feature object has missing or additional keys")
        return out
    def score_scene(self, *, film_id:str, scene_id:str, scene_title:str, scene_text:str)->MeasurementResult:
        key=self._key(film_id,scene_id,scene_title,scene_text)
        if self.use_cache:
            with self._cache_lock:
                row=self.cache.get(key)
            if row is not None:
                return MeasurementResult("measured",dict(row["features"]),0,row.get("response_text"),key,None,row["provenance"],True)
        prompt=self._render(film_id,scene_id,scene_title,scene_text); decoding=self.protocol.decoding
        attempts=1+max(0,int(decoding.get("schema_retry_count",1))); last_error=None; response=None
        owns=False; client=self.client
        if client is None:
            client=OpenAICompatibleClient(self.protocol.model["base_url"],float(decoding.get("timeout_seconds",600)),int(decoding.get("concurrency",8))); owns=True
        try:
            for idx in range(attempts):
                try:
                    response=client.generate(prompt=prompt,model=self.protocol.model["alias"],schema=self.protocol.schema,decoding=decoding,system_instruction=self.protocol.system_instruction,response_schema_name=self.protocol.response_schema_name)
                    features=self._parse(response)
                    prov={**self.protocol.manifest(),"film_id":film_id,"scene_id":scene_id,"scene_title":scene_title,"attempt":idx+1}
                    if self.cache_path:
                        with self._cache_lock:
                            self.cache[key]={"features":features,"response_text":response,"provenance":prov}
                            self._cache_dirty=True
                    return MeasurementResult("measured",features,idx+1,response,key,None,prov,False)
                except Exception as exc: last_error=str(exc)
        finally:
            if owns: client.close()
        prov={**self.protocol.manifest(),"film_id":film_id,"scene_id":scene_id,"scene_title":scene_title}
        return MeasurementResult("measurement_ineligible",None,attempts,response,key,last_error,prov,False)

    def flush_cache(self) -> None:
        if not self.cache_path:
            return
        with self._cache_lock:
            if not self._cache_dirty:
                return
            write_json(self.cache_path,self.cache)
            self._cache_dirty=False
