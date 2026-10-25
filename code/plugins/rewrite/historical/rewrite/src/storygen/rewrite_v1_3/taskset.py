from pydantic import BaseModel,Field,ConfigDict
from typing import Any
import json
from pathlib import Path
class Task(BaseModel):
 model_config=ConfigDict(extra='allow')
 task_id:str;source_film_id:str;reference_film_id:str;source_script_path:str;source_feature_path:str;reference_feature_path:str;source_start_scene_id:str;source_end_scene_id:str;reference_start_scene_id:str;reference_end_scene_id:str;source_scene_ids:list[str];reference_scene_ids:list[str];selected_features:list[str];variant:str;interval_type:str;difficulty_score:float;difficulty_bucket:str;base_interval_id:str|None=None;pair_key:str|None=None;feature_axis:str|None=None
class Taskset(BaseModel):
 model_config=ConfigDict(extra='allow')
 taskset_id:str='taskset';tasks:list[Task]=Field(default_factory=list);feature_set_id:str|None=None;feature_extraction_signature:str|None=None

def load_taskset(path:Path)->Taskset:return Taskset.model_validate(json.loads(path.read_text()))
