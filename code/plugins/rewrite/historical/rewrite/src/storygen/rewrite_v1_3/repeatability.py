"""E03 orchestration only; canonical runner, engine and transport are delegates.

Temporary dependency bindings are scoped to one sequential runner invocation.
They add request seeds/audit and progress, without changing its scheduler, prompt,
repair, validation, connection pool or semaphore. No generation cache exists.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import threading
from unittest.mock import patch

import numpy as np

from .provenance import sha256_json
from storygen.services.vllm_client import _messages, _translate_options

SELECTION_SEED = 4203
SEED_SCHEDULE = {'CG-v1': [43001, 43002, 43003, 43004, 43005],
                 'DP-v1': [44001, 44002, 44003, 44004, 44005]}
SELECTION_FIELDS = ('task_id', 'base_interval_id', 'selected_features',
                    'source_film_id', 'interval_type', 'source_scene_ids')


def select_tasks(tasks):
    """Inspect selection metadata only; never consult success or metric fields."""
    metadata = [{k: t[k] for k in SELECTION_FIELDS} for t in tasks]
    groups = defaultdict(list)
    for task in metadata:
        groups[task['base_interval_id']].append(task)
    features = sorted({t['selected_features'][0] for t in metadata})
    if len(metadata) != 240 or len(groups) != 48 or len(features) != 5 or any(
            len(g) != 5 or {t['selected_features'][0] for t in g} != set(features)
            for g in groups.values()):
        raise RuntimeError('E03 requires the frozen 48-by-five task population')
    rng = np.random.default_rng(SELECTION_SEED)
    bases = sorted(groups); rng.shuffle(bases)
    axes = (features * 10)[:48]; rng.shuffle(axes)
    cg = [next(t for t in groups[base] if t['selected_features'] == [axis])
          for base, axis in zip(bases, axes)]
    cg.sort(key=lambda t: t['task_id'])
    lengths = {length: [t for t in cg if t['interval_type'] == length]
               for length in ('short', 'medium', 'long')}
    if any(len(v) != 16 for v in lengths.values()) or len({t['source_film_id'] for t in cg}) != 10:
        raise RuntimeError('E03 frozen length/film balance mismatch')
    for trial in range(100000):
        dp = [items[int(i)] for items in lengths.values()
              for i in rng.choice(len(items), 4, replace=False)]
        counts = Counter(t['selected_features'][0] for t in dp)
        if sorted(counts.values()) == [2, 2, 2, 3, 3] and len({t['source_film_id'] for t in dp}) == 10:
            dp.sort(key=lambda t: t['task_id'])
            return {'CG-v1': cg, 'DP-v1': dp}, trial + 1
    raise RuntimeError('Balanced matched subset not established; STOP')


def request_seed(condition, repetition, task_id, scene_id, attempt):
    """Stable positive int32 seed, excluding llama.cpp's random sentinel -1."""
    master = SEED_SCHEDULE[condition][repetition - 1]
    raw = f'E03.seed.v1|{master}|{condition}|{task_id}|{scene_id}|{attempt}'
    return 1 + int.from_bytes(hashlib.sha256(raw.encode()).digest()[:8], 'big') % 2147483646


def payload_for(prompt, model, *, system=None, format_schema=None,
                format_json=False, options=None, **_):
    """Same request projection used by the unmodified Gemma canonical transport."""
    payload = dict(model=model, messages=_messages(system=system, prompt=prompt,
                   model=model, structured=bool(format_schema or format_json)), stream=False)
    payload.update(_translate_options(options or {}))
    if format_schema is not None:
        payload['response_format'] = dict(type='json_schema', json_schema=dict(
            name='storygen_response', strict=True, schema=format_schema))
    elif format_json:
        payload['response_format'] = {'type': 'json_object'}
    return payload


class SeededClient:
    def __init__(self, delegate, *, condition, repetition, tasks, primary_requests,
                 context, audit_path, experiment_id, output, abort=None):
        self.delegate = delegate
        self.condition = condition; self.repetition = repetition
        self.tasks = {t['task_id']: t for t in tasks}
        self.primary = {(p['task_id'], p['scene_id']): p for p in primary_requests
                        if p['condition'] == condition}
        self.context = context; self.experiment_id = experiment_id; self.output = output
        self.abort = abort or threading.Event()
        self.attempts = Counter(); self.lock = threading.Lock()
        Path(audit_path).parent.mkdir(parents=True, exist_ok=True)
        self.audit = Path(audit_path).open('x')

    def generate(self, prompt, model, **kwargs):
        if self.abort.is_set():
            raise RuntimeError('E03 stopped after a provenance invariant failure')
        task_id = self.context.task_id
        scene_id = (kwargs.get('request_metadata') or {})['scene_id']
        with self.lock:
            self.attempts[task_id, scene_id] += 1
            attempt = self.attempts[task_id, scene_id]
        if attempt > 2:
            self.abort.set()
            raise RuntimeError('E03 canonical bounded repair limit exceeded')
        payload = payload_for(prompt, model, **kwargs)
        if attempt == 1 and sha256_json(payload) != self.primary[task_id, scene_id]['request_contract_hash']:
            self.abort.set()
            raise RuntimeError('E03 frozen primary prompt/request mismatch before inference')
        seed = request_seed(self.condition, self.repetition, task_id, scene_id, attempt)
        kwargs['options'] = {**(kwargs.get('options') or {}), 'seed': seed}
        kwargs['request_metadata'] = {**(kwargs.get('request_metadata') or {}),
                                      'e03_sampling_seed': seed, 'e03_repetition': self.repetition}
        task = self.tasks[task_id]
        record = dict(experiment_id=self.experiment_id, condition=self.condition,
            task_id=task_id, base_interval_id=task['base_interval_id'], repetition_id=self.repetition,
            scene_id=scene_id, attempt=attempt, attempt_kind='primary' if attempt == 1 else 'repair',
            sampling_seed=seed, applied_at='OpenAI /v1/chat/completions JSON seed',
            prompt_hash=sha256_json(payload['messages']),
            request_sha256=sha256_json({**payload, 'seed': seed}), generation_settings=kwargs['options'],
            model_id=model, output_path=str(self.output / 'tasks' / task_id),
            completion_status='REQUEST_STARTED', failure_reason=None)
        self._write(record)
        try:
            result = self.delegate.generate(prompt, model, **kwargs)
        except Exception as exc:
            self._write({**record, 'completion_status': 'TRANSPORT_FAILED', 'failure_reason': str(exc)})
            print(f'\nE03 REQUEST FAILED {self.condition}/{self.repetition}/{task_id}/{scene_id}: {exc}', flush=True)
            raise
        self._write({**record, 'completion_status': 'RESPONSE_RECEIVED',
                     'raw_response_sha256': 'sha256:' + hashlib.sha256(result.encode()).hexdigest()})
        return result

    def _write(self, record):
        with self.lock:
            self.audit.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + '\n')
            self.audit.flush()

    def close(self):
        try:
            self.delegate.close()
        finally:
            self.audit.close()


@contextmanager
def runner_bindings(*, runner, config, condition, repetition, output, client_factory=None):
    """Scope audit/seed/progress to E03; restore all bindings even on interruption."""
    from storygen_feature.progress import ProgressReporter
    canonical_client = client_factory or runner.VLLMClient
    canonical_engine = runner.run_per_scene_rewrite_from_files
    context = threading.local()
    abort = threading.Event()
    tasks = json.loads(Path(config['tasksets'][condition]).read_text())['tasks']
    requests = json.loads(Path(config['primary_requests']).read_text())
    frozen_plans = Path(config['frozen_plans'])

    def factory(**kwargs):
        # Same persistent pooled client and same semaphore/concurrency as runner.
        return SeededClient(canonical_client(**kwargs), condition=condition, repetition=repetition,
            tasks=tasks, primary_requests=requests, context=context,
            audit_path=output/'E03_REQUESTS.jsonl', experiment_id=config['experiment_id'], output=output, abort=abort)

    def engine(**kwargs):
        if abort.is_set():
            raise RuntimeError('E03 stopped after a provenance invariant failure')
        context.task_id = Path(kwargs['plan_path']).parent.name
        actual = json.loads(Path(kwargs['plan_path']).read_text())
        expected = json.loads((frozen_plans/'tasks'/context.task_id/'transfer_plan.json').read_text())
        if actual != expected:
            abort.set()
            raise RuntimeError('E03 historical transfer plan changed before inference')
        return canonical_engine(**kwargs)

    class Progress:
        def __init__(self, total):
            self.reporter = ProgressReporter(label=f'E03 {condition} repeat {repetition}/5', total=total, mode='always')

        def tick(self, label):
            tid, sid = label.split('/')
            path = output/'tasks'/tid/'per_scene'/sid/'scene_summary.json'
            succeeded = path.is_file() and json.loads(path.read_text()).get('succeeded') is True
            self.reporter.request_finished(label, successful=succeeded)
            if not succeeded:
                print('\nE03 SCENE FAILED: ' + label, flush=True)

        def finish(self):
            self.reporter.finish()

    with patch.object(runner, 'VLLMClient', factory), patch.object(runner, 'Progress', Progress), \
            patch.object(runner, 'run_per_scene_rewrite_from_files', engine):
        yield abort


def generation_records(config, condition, repetition, output):
    """One auditable row for every planned task, including task-level failures."""
    tasks = json.loads(Path(config['tasksets'][condition]).read_text())['tasks']
    primary = json.loads(Path(config['primary_requests']).read_text())
    records = []
    for task in tasks:
        directory = output/'tasks'/task['task_id']
        status_path = directory/'phase_status.json'; failure_path = directory/'rewrite_failure.json'
        complete = status_path.is_file() and json.loads(status_path.read_text()).get('rewrite_completed') is True
        failure = json.loads(failure_path.read_text()) if failure_path.is_file() else None
        hashes = [p['prompt_hash'] for p in primary if p['condition'] == condition and p['task_id'] == task['task_id']]
        records.append(dict(experiment_id=config['experiment_id'], condition=condition,
            task_id=task['task_id'], base_interval_id=task['base_interval_id'], repetition_id=repetition,
            model_id=config['gemma_server']['model_alias'], checkpoint_sha256=config['models']['gemma']['sha256'],
            prompt_hash=sha256_json(hashes), generation_settings=config['decoding'],
            sampling_seed_or_rng_status='RECORDED_REQUEST_SEEDS',
            primary_seeds={sid: request_seed(condition, repetition, task['task_id'], sid, 1)
                           for sid in task['source_scene_ids']}, output_path=str(directory),
            completion_status='SUCCESS' if complete else 'GENERATION_FAILED',
            failure_reason=None if complete else (failure or {'error': 'missing canonical completed status'})))
    return records
