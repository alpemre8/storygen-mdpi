"""NG-v0 orchestration around the unchanged canonical scene validator/transport."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
import json
import threading
import time

from storygen.schemas.transfer import TransferPlan, SceneRewriteDirective
from storygen.services.rewrite_engine import load_selected_scenes
from storygen.services.per_scene_rewrite_engine import run_per_scene_rewrite_from_files
from storygen.services.vllm_client import VLLMClient
from .provenance import prompt_provenance, sha256_file, sha256_json
from .runner import write_json


def group_tasks(tasks, script_paths):
    """Deterministic source-only generation units; original task identities stay intact."""
    if len(tasks) != 240 or len({t['task_id'] for t in tasks}) != 240:
        raise ValueError('Expected 240 unique original task IDs')
    groups = {}
    for task in tasks:
        groups.setdefault(task['base_interval_id'], []).append(task)
    if len(groups) != 48:
        raise ValueError('Expected 48 base intervals')
    units = []
    fields = ('source_film_id', 'source_scene_ids', 'source_start_scene_id',
              'source_end_scene_id', 'source_scene_count', 'interval_type')
    for base, members in sorted(groups.items()):
        if Path(base).name != base or len(members) != 5:
            raise ValueError('Invalid base identity or group size')
        first = members[0]
        if len({t['feature_axis'] for t in members}) != 5:
            raise ValueError('Five distinct feature evaluations required')
        scenes = None
        for task in members:
            if any(task[k] != first[k] for k in fields):
                raise ValueError('Source interval mismatch within base: ' + base)
            path = script_paths[task['source_script_path']]
            selected = load_selected_scenes(path, task['source_scene_ids'])
            projection = [(s.scene_id, s.scene_index, s.title, s.content) for s in selected]
            if scenes is not None and projection != scenes:
                raise ValueError('Source text/order mismatch within base: ' + base)
            scenes = projection
        ids = first['source_scene_ids']
        if len(set(ids)) != len(ids) or ids[0] != first['source_start_scene_id'] or ids[-1] != first['source_end_scene_id']:
            raise ValueError('Invalid ordered source interval')
        units.append(dict(base_interval_id=base, task_ids=[t['task_id'] for t in members],
                          source_film_id=first['source_film_id'], source_scene_ids=ids,
                          source_script_path=str(script_paths[first['source_script_path']]),
                          source_script_sha256=sha256_file(script_paths[first['source_script_path']]),
                          source_projection_sha256=sha256_json(scenes),
                          scene_positions=len(ids),
                          truncated_scene_ids=[s[0] for s in scenes if len(s[3]) > 12000]))
    if sum(u['scene_positions'] for u in units) != 400:
        raise ValueError('Expected 400 planned source scene positions')
    return units


def source_only_plan(unit):
    scenes = load_selected_scenes(unit['source_script_path'], unit['source_scene_ids'])
    return TransferPlan(
        run_id=unit['base_interval_id'], feature_source_path='<unused:NG-v0>',
        selected_features=[], source_scene_ids=unit['source_scene_ids'], reference_scene_ids=[],
        source_current_curve={}, reference_curve={}, resampled_target_curve={},
        per_scene_target_values=[SceneRewriteDirective(scene_id=s.scene_id, scene_index=s.scene_index,
            title=s.title, current_values={}, targets={}, deltas={}, directive='') for s in scenes],
        preservation_constraints=['Preserve source identities, relationships, setting, core events, outcome and continuity.'],
        planner_version='NG-v0.source-only-projection/1.0',
    )


class SceneProgress:
    def __init__(self, total):
        self.total, self.done, self.success, self.failure = total, 0, 0, 0
        self.start, self.lock = time.monotonic(), threading.Lock()

    def tick(self, task_dir, scene_id):
        with self.lock:
            summary = task_dir / 'per_scene' / scene_id / 'scene_summary.json'
            ok = summary.is_file() and json.loads(summary.read_text()).get('succeeded') is True
            self.done += 1
            self.success += int(ok)
            self.failure += int(not ok)
            elapsed = time.monotonic() - self.start
            rate = self.done / elapsed if elapsed else 0
            def duration(seconds):
                n = int(seconds); h, n = divmod(n, 3600); m, s = divmod(n, 60)
                return f'{h:02d}:{m:02d}:{s:02d}'
            eta = duration((self.total - self.done) / rate) if rate else '--:--:--'
            print(f'\rNG-v0 scenes={self.done}/{self.total} elapsed={duration(elapsed)} '
                  f'ETA={eta} success={self.success} failure={self.failure} throughput={rate:.3f}/s',
                  end='', flush=True)


def run_ng(config, *, client=None):
    """Called only by the author-run Stage A, after its runtime preflight."""
    root = Path(config['rewrite_output'])
    root.mkdir(parents=True, exist_ok=False)  # No overwrite or resume path.
    units = json.loads(Path(config['mapping']).read_text())['units']
    provenance = prompt_provenance(Path(__file__).resolve().parents[3], 'NG-v0')
    progress = SceneProgress(400)
    owned_client = client is None
    client = client or VLLMClient(base_url=config['gemma_server']['base_url'],
                                 timeout_seconds=900, max_in_flight=4)
    completed, failures = [], []

    def one(unit):
        base = unit['base_interval_id']; td = root / 'tasks' / base
        td.mkdir(parents=True, exist_ok=False)
        write_json(td / 'task.json', next(t for t in config['base_tasks'] if t['task_id'] == base))
        write_json(td / 'transfer_plan.json', source_only_plan(unit).model_dump(mode='json'))
        try:
            run_per_scene_rewrite_from_files(
                plan_path=td / 'transfer_plan.json', script_path=unit['source_script_path'],
                output_path=td / 'rewritten_scenes.json', model=config['gemma_server']['model_alias'],
                vllm_base_url=config['gemma_server']['base_url'], temperature=.2, client=client,
                max_scene_chars=12000, schema_retry_count=1, allow_partial_task_output=False,
                prompt_strategy='no_guidance', prompt_version='v0', rewrite_timeout_seconds=900,
                rewrite_format_mode='schema', rewrite_max_tokens=4096, generation_concurrency=1,
                progress_callback=lambda sid: progress.tick(td, sid))
            write_json(td / 'phase_status.json', dict(rewrite_completed=True, prompt_contract_id='NG-v0'))
            return dict(base_interval_id=base, rewrite_completed=True)
        except Exception as exc:
            failure = dict(base_interval_id=base, stage='rewrite', root_cause_type=type(exc).__name__, error=str(exc))
            write_json(td / 'rewrite_failure.json', failure)
            return failure

    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            for future in as_completed([executor.submit(one, unit) for unit in units]):
                value = future.result()
                (completed if value.get('rewrite_completed') else failures).append(value)
    finally:
        if owned_client:
            client.close()
        print()
    fs = json.loads(Path(config['reference']['path']).read_text())
    manifest = dict(contract_id='storygen.rewrite-run', contract_version='1.3',
        rewrite_protocol_id='rewrite-v1.3', prompt_contract_id='NG-v0', prompt_provenance=provenance,
        model=dict(served_alias=config['gemma_server']['model_alias'],
                   exact_file=config['gemma_server']['model_path'], file_sha256=config['models']['gemma']['sha256'], quantization='Q4_K_M'),
        server_manifest=dict(path=config['gemma_manifest'], content=config['gemma_server'], sha256=sha256_file(Path(config['gemma_manifest']))),
        feature_set_manifest=dict(**config['reference'], measurement=fs['measurement']),
        taskset=dict(path=config['base_runtime'], sha256=sha256_file(Path(config['base_runtime'])), task_count=48),
        frozen_evaluation_taskset=config['frozen_taskset'], mapping_sha256=sha256_file(Path(config['mapping'])),
        generation_unit='base_interval_id', planned_scene_requests=400,
        decoding=dict(temperature=.2, max_tokens=4096, schema_retry_count=1, concurrency=4, timeout_seconds=900),
        tasks_completed=len(completed), tasks_failed=len(failures), failures=sorted(failures,key=lambda r:r['base_interval_id']),
        created_at=datetime.now(timezone.utc).isoformat())
    write_json(root / 'rewrite_run_manifest.json', manifest)
    return manifest
