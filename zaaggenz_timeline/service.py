"""Bounded offline renders; immutable full-phrase state precedes region extraction."""
from __future__ import annotations
from collections import OrderedDict
from dataclasses import asdict
import hashlib
import io
import threading
import secrets
import time
import numpy as np
from scipy.io import wavfile
from zaaggenz_contracts import digest
from zaaggenz_contracts.music import beat_to_sample
from zaaggenz_jobs import JobScheduler, SchedulerLimits, JobClass, RenderArtifact, JobError, JobCancelled
from zaaggenz_melody import MelodicRenderSpec, make_render_executor
from zaaggenz_melody.render import melodic_cache_key
from .model import (TimelineDocument,apply_source_preset,source_preset_catalogue,compile_recipe,render_region,memory_estimate,text,describe,default_document)


def scheduler_limits():
    """Authoritative local interactive/background scheduler envelope for timeline consumers."""
    return SchedulerLimits(interactive_workers=1, background_workers=1,
                           max_queued_jobs=8, max_background_queued_jobs=4,
                           max_history_jobs=16)


def region_cache_key(recipe, region):
    return digest({'domain':'zaaggenz.timeline-region-v1',
                   'full_cache_key':melodic_cache_key(recipe), 'region':region})


def region_executor(recipe, revision, region):
    """Render the full phrase, then crop: tails crossing the selection start remain."""
    full_executor = make_render_executor(recipe, MelodicRenderSpec(), revision)
    key = region_cache_key(recipe, region)
    tm = recipe.to_dict()['time_map']
    start = beat_to_sample(tm, region['start_beat']) - beat_to_sample(tm, '0/1')
    end = beat_to_sample(tm, region['end_beat']) - beat_to_sample(tm, '0/1')
    if end <= start:
        raise ValueError('selection rounds to fewer than one sample')

    def execute(ctx):
        full = full_executor(ctx)
        ctx.check_cancelled()
        audio = np.frombuffer(full.audio_bytes, dtype='<f4')[start:end]
        pcm = audio.tobytes()
        asset = {**full.asset, 'frame_count': len(audio), 'content_sha256': hashlib.sha256(pcm).hexdigest()}
        bins = max(1, min(480, len(audio)))
        edges = np.linspace(0, len(audio), bins + 1, dtype=int)
        waveform = [float(np.max(np.abs(audio[edges[i]:edges[i+1]]), initial=0)) for i in range(bins)]
        # Events beginning before the selection remain labelled as such; offset may be negative.
        events = [{**event, 'onset_sample': event['onset_sample'] - start}
                  for event in full.scopes['events']
                  if event['onset_sample'] < end and event['onset_sample'] + max(event['gate_samples'], event.get('output_samples', 0)) > start]
        scopes = {'waveform': waveform, 'events': events, 'region': region,
                  'offset_sample': start, 'diagnostics': {**full.scopes['diagnostics'],
                    'region_samples': len(audio), 'region_peak': float(np.max(np.abs(audio), initial=0)),
                    'render_policy': 'whole-phrase-then-crop'}}
        ctx.check_cancelled()
        return RenderArtifact(revision, recipe.sha256, 'synth', key, pcm, asset, scopes)
    return execute


class TimelineService:
    """Timeline job owner.

    A standalone service owns its scheduler.  A composed runtime may inject one
    shared scheduler; in that case this service never shuts the scheduler down.
    Job ownership remains service-local so one workspace cannot cancel or read
    another workspace's jobs merely because they share the scheduler.
    """
    _MAX_OWNED_JOB_IDS = 64

    def __init__(self, scheduler=None, *, session=None, debounce_seconds=.12):
        if scheduler is not None and not isinstance(scheduler, JobScheduler):
            raise TypeError('scheduler must be a JobScheduler')
        from zaaggenz_runtime.session import RuntimeSession
        if session is not None and not isinstance(session, RuntimeSession):
            raise TypeError('session must be a RuntimeSession')
        if type(debounce_seconds) not in (int, float) or not 0 <= debounce_seconds <= .5:
            raise ValueError('debounce_seconds must be finite in [0,.5]')
        self.session = RuntimeSession(default_document()) if session is None else session
        self._debounce_seconds = float(debounce_seconds)
        self._cache_namespace = secrets.token_hex(16)
        self._owns_scheduler = scheduler is None
        self.scheduler = JobScheduler(scheduler_limits()) if scheduler is None else scheduler
        self._jobs = OrderedDict()
        self._jobs_lock = threading.RLock()
        self._closed = False

    @property
    def owns_scheduler(self):
        return self._owns_scheduler

    def _remember_job(self, job_id, binding):
        with self._jobs_lock:
            self._jobs[job_id] = binding
            self._jobs.move_to_end(job_id)
            if len(self._jobs) <= self._MAX_OWNED_JOB_IDS:
                return
            # The scheduler itself retains only bounded history.  Drop only
            # terminal/evicted ownership records; active records are never lost.
            for candidate in list(self._jobs):
                if len(self._jobs) <= self._MAX_OWNED_JOB_IDS:
                    break
                try:
                    state = self.scheduler.snapshot(candidate).state
                except JobError:
                    self._jobs.pop(candidate, None)
                    continue
                if state in ('completed', 'failed', 'cancelled'):
                    self._jobs.pop(candidate, None)

    def _require_job(self, job_id):
        with self._jobs_lock:
            if job_id not in self._jobs:
                raise JobError('job is not owned by timeline service')

    def _current_locked(self, binding):
        if binding['revoked'] or self._closed:
            return False
        generation, revision = self.session.current_identity()
        return generation == binding['generation'] and (
            not binding['authoritative'] or revision == binding['revision_id'])

    def _accept_locked(self, document):
        before = self.session.current_identity()
        snapshot = self.session.accept_document(document)
        if self.session.current_identity() != before:
            for job_id, binding in self._jobs.items():
                if not self._current_locked(binding):
                    try:self.scheduler.cancel(job_id)
                    except JobError:pass  # evicted terminal evidence, never new work
        return snapshot

    def accept_document(self, data):
        """Validate/admit the complete document before changing session authority."""
        document = data if isinstance(data, TimelineDocument) else TimelineDocument(data)
        recipe = compile_recipe(document)
        memory_estimate(recipe)
        with self._jobs_lock:
            return self._accept_locked(document)

    def presets(self):
        return source_preset_catalogue()

    def apply_preset(self,data,preset_id):
        document=apply_source_preset(TimelineDocument(data),preset_id)
        recipe=compile_recipe(document)
        estimate = memory_estimate(recipe)
        with self._jobs_lock:
            session = self._accept_locked(document)
        return {'document':document.to_dict(),**describe(document),'recipe_sha256':recipe.sha256,
                'estimated_memory_bytes':estimate,'session':session}

    def validate(self, data):
        document = TimelineDocument(data)
        recipe = compile_recipe(document)
        estimate = memory_estimate(recipe)
        with self._jobs_lock:
            session = self._accept_locked(document)
        return {**describe(document), 'recipe_sha256': recipe.sha256,
                'estimated_memory_bytes': estimate, 'session': session}

    def submit(self, data, region=None, name='Render', *, authoritative=True):
        """Same exact executor for Compose preview, saved rerender and WAV export.

        A sidecar may explicitly request a non-authoritative proposal; that job
        cannot replace the RuntimeSession. Playback is still bound to the
        session generation from which the proposal was requested.
        """
        if type(authoritative) is not bool:
            raise TypeError('authoritative must be boolean')
        text(name, 'render name')
        document = TimelineDocument(data)
        revision = document.revision_id
        recipe = compile_recipe(document)
        region = render_region(recipe, region)
        estimate = memory_estimate(recipe)  # never discount selected context
        key = region_cache_key(recipe, region)
        request_key = digest({'domain':'zaaggenz.timeline-owned-request-v1',
                              'owner':self._cache_namespace, 'revision':revision,
                              'recipe':recipe.sha256, 'cache_key':key, 'authoritative':authoritative})
        canonical = region_executor(recipe, revision, region)
        expected = (revision, recipe.sha256, key, 'synth')
        response = {'revision_id':revision, 'recipe_sha256':recipe.sha256,
                    'cache_key':key, 'region':region, 'name':name,
                    'estimated_memory_bytes':estimate,
                    'context_policy':'whole-phrase-then-crop'}
        with self._jobs_lock:
            if self._closed:raise JobError('timeline service is closed')
            # Identical pending requests adopt the same computation. Named full
            # and region outputs of one revision may coexist; a new document
            # supersedes obsolete revisions, not other workspaces' jobs.
            for job_id, previous in reversed(self._jobs.items()):
                if previous['request_key'] == request_key and self._current_locked(previous):
                    try:snapshot = self.scheduler.snapshot(job_id)
                    except JobError:continue
                    if snapshot.state in ('queued', 'running'):
                        return {**response, 'job_id':job_id, 'adopted':True,
                                'session':self.session.snapshot()}
            binding = {'generation':None, 'revision_id':revision, 'request_key':request_key,
                       'authoritative':authoritative, 'revoked':False}
            owner = self
            class GuardedContext:
                def __init__(self, context):
                    self.context = context
                    self.job_id = context.job_id
                    self.token = context.token
                def check_cancelled(self):
                    self.context.check_cancelled()
                    with owner._jobs_lock:
                        if not owner._current_locked(binding):
                            raise JobCancelled('stale or cancelled Compose render')
                def progress(self, value):
                    self.check_cancelled()
                    self.context.progress(value)
            def execute(context):
                ctx = GuardedContext(context)
                ctx.check_cancelled()
                # Coalesce rapid edits before heavy synthesis. Cancellation is
                # observed at <=10ms polling intervals during this idle delay.
                deadline = time.monotonic() + owner._debounce_seconds
                while time.monotonic() < deadline:
                    ctx.check_cancelled()
                    time.sleep(min(.01, max(0., deadline-time.monotonic())))
                ctx.check_cancelled()
                cached = owner.scheduler.cached_render(request_key, job_id=context.job_id)
                result = canonical(ctx) if cached is None else cached
                if not isinstance(result, RenderArtifact) or (
                    result.revision_id, result.recipe_sha256, result.cache_key, result.product) != expected:
                    raise JobError('timeline render/cache artifact identity mismatch')
                ctx.check_cancelled()
                return result
            # Admission happens BEFORE changing the session or cancelling its
            # last coherent work. The worker cannot pass the lock until the
            # exact immutable binding below is installed.
            before_generation, before_revision = self.session.current_identity()
            generation = before_generation + int(authoritative and before_revision != revision)
            job_id = self.scheduler.submit(JobClass.RENDER, revision, execute,
                estimated_memory_bytes=estimate, generation=generation, dedupe_key=request_key)
            session = self._accept_locked(document) if authoritative else self.session.snapshot()
            binding['generation'] = session['generation']
            self._remember_job(job_id, binding)
            return {**response, 'job_id':job_id, 'adopted':False, 'session':session}

    def status(self, job_id):
        with self._jobs_lock:
            self._require_job(job_id)
            snapshot = self.scheduler.snapshot(job_id)
            response = asdict(snapshot)
            binding = self._jobs[job_id]
            if binding['revoked']:
                return {**response, 'state':'cancelled', 'accepted':False}
            if not self._current_locked(binding):
                return {**response, 'state':'stale', 'accepted':False}
            response['accepted'] = snapshot.state == 'completed'
            if response['accepted']:
                response['artifact'] = self.artifact(job_id).metadata()
            return response

    def artifact(self, job_id):
        """Return an exact completed RenderArtifact owned by this timeline."""
        self._require_job(job_id)
        result = self.scheduler.result(job_id)
        if not isinstance(result, RenderArtifact):
            raise JobError('timeline job did not produce a RenderArtifact')
        return result

    def wave(self, job_id):
        with self._jobs_lock:
            self._require_job(job_id)
            if not self._current_locked(self._jobs[job_id]):
                raise JobError('stale or cancelled Compose audio cannot be published')
            result = self.artifact(job_id)
        buffer = io.BytesIO()
        wavfile.write(buffer, result.asset['sample_rate_hz'], np.frombuffer(result.audio_bytes, dtype='<f4'))
        # A revision can change while encoding; guard again before handoff.
        with self._jobs_lock:
            if not self._current_locked(self._jobs[job_id]):
                raise JobError('stale or cancelled Compose audio cannot be published')
            return buffer.getvalue(), result.revision_id

    def cancel(self, job_id):
        with self._jobs_lock:
            self._require_job(job_id)
            self._jobs[job_id]['revoked'] = True
            self.scheduler.cancel(job_id)
            return True

    def close(self):
        if self._closed:
            return
        with self._jobs_lock:
            self._closed = True
            for job_id in self._jobs:
                try:self.scheduler.cancel(job_id)
                except JobError:pass
        if self._owns_scheduler:
            self.scheduler.shutdown(cancel=True, timeout=5)
