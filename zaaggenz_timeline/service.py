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
from zaaggenz_project import Project
from zaaggenz_jobs import JobScheduler, SchedulerLimits, JobClass, RenderArtifact, JobError, JobCancelled
from zaaggenz_melody import MelodicRenderSpec, make_render_executor
from zaaggenz_melody.render import melodic_cache_key
from .model import (TimelineDocument,apply_source_preset,source_preset_catalogue,compile_recipe,render_region,memory_estimate,text,describe,default_document)
from .rack_edit import edit_rack, editor_state


def scheduler_limits():
    """Authoritative local interactive/background scheduler envelope for timeline consumers."""
    return SchedulerLimits(interactive_workers=1, background_workers=1,
                           max_queued_jobs=8, max_background_queued_jobs=4,
                           max_history_jobs=16)


def _post_master_band_monitor(full, band, mode, crossovers, cache_key, ctx):
    """Filtered final-mix listening only; never change the rack or export."""
    from zaaggenz_dsp.band_router import BAND_NAMES, FILTER_POLICY
    from zaaggenz_dsp.multiband import split_bands
    if len(full.audio_bytes) < 8 * 4:
        raise JobError('band monitoring requires at least eight frames')
    ctx.check_cancelled()
    original = np.frombuffer(full.audio_bytes, dtype='<f4')
    selected = split_bands(original, full.asset['sample_rate_hz'], crossovers)[BAND_NAMES.index(band)]
    ctx.check_cancelled()
    result = selected if mode == 'solo' else original.astype(np.float64) - selected
    if not np.isfinite(result).all():
        raise JobError('band monitor produced nonfinite audio')
    pcm = np.asarray(result, dtype='<f4').tobytes()
    asset = {**full.asset, 'content_sha256': hashlib.sha256(pcm).hexdigest()}
    audio = np.frombuffer(pcm, dtype='<f4')
    bins = max(1, min(360, len(audio)))
    edges = np.linspace(0, len(audio), bins + 1, dtype=int)
    waveform = [float(np.max(np.abs(audio[edges[i]:edges[i+1]]), initial=0)) for i in range(bins)]
    scopes = {'waveform': waveform, 'events': full.scopes.get('events', []),
              'diagnostics': {'master_peak': float(np.max(np.abs(audio), initial=0)),
                'monitor': {'policy':'post-master filtering; non-authoritative listening only',
                            'band':band, 'mode':mode, 'filter_method':FILTER_POLICY,
                            'crossovers_hz':list(crossovers)}}}
    ctx.check_cancelled()
    return RenderArtifact(full.revision_id, full.recipe_sha256, 'synth',
                          cache_key, pcm, asset, scopes)


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

    def _remember_job(self, job_id, binding=None):
        # Retained internal consumers may hand us an already-completed render
        # from the shared scheduler.  Never restore the old unbound ownership
        # semantics: derive a complete non-authoritative binding from the exact
        # RenderArtifact and current session generation, or fail closed.
        if binding is None:
            result = self.scheduler.result(job_id)
            if not isinstance(result, RenderArtifact):
                raise JobError('cannot remember an unbound non-render timeline job')
            generation, _ = self.session.current_identity()
            binding = {'generation':generation, 'revision_id':result.revision_id,
                       'request_key':result.cache_key, 'authoritative':False,
                       'revoked':False}
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

    def _admit_recipe(self, recipe):
        """Reject permanently unrenderable edits before replacing current audio.

        Compose submits RENDER jobs on the interactive lane, so its permanent
        capacity is the scheduler's per-job bound (not the PREVIEW reserve).
        Validation does not reserve a queue slot; submit still checks current
        queue capacity before accepting the authoritative document.
        """
        estimate = memory_estimate(recipe)
        if estimate > self.scheduler.limits.max_job_memory_bytes:
            raise JobError('timeline render memory estimate exceeds job memory bound')
        return estimate

    def accept_document(self, data):
        """Validate/admit the complete document before changing session authority."""
        document = data if isinstance(data, TimelineDocument) else TimelineDocument(data)
        recipe = compile_recipe(document)
        self._admit_recipe(recipe)
        with self._jobs_lock:
            return self._accept_locked(document)

    def presets(self):
        return source_preset_catalogue()

    def apply_preset(self,data,preset_id):
        document=apply_source_preset(TimelineDocument(data),preset_id)
        recipe=compile_recipe(document)
        estimate = self._admit_recipe(recipe)
        with self._jobs_lock:
            session = self._accept_locked(document)
        return {'document':document.to_dict(),**describe(document),'recipe_sha256':recipe.sha256,
                'estimated_memory_bytes':estimate,'session':session, 'rack_editor':editor_state(document)}

    def validate(self, data):
        document = TimelineDocument(data)
        recipe = compile_recipe(document)
        estimate = self._admit_recipe(recipe)
        with self._jobs_lock:
            session = self._accept_locked(document)
        return {**describe(document), 'recipe_sha256': recipe.sha256,
                'estimated_memory_bytes': estimate, 'session': session,
                'rack_editor': editor_state(document)}

    def propose_rack_edit(self, data, action):
        """Return a validated, memory-admitted proposal without changing session.

        The browser must adopt the resulting document through the ordinary
        /validate route; a delayed rack response cannot publish stale state.
        """
        document = edit_rack(TimelineDocument(data), action)
        recipe = compile_recipe(document)
        estimate = self._admit_recipe(recipe)
        return {'document': document.to_dict(), **describe(document),
                'recipe_sha256': recipe.sha256,
                'estimated_memory_bytes': estimate,
                'rack_editor': editor_state(document)}

    def submit(self, data, region=None, name='Render', *, authoritative=True, band_monitor=None):
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
        estimate = self._admit_recipe(recipe)  # never discount selected context
        key = region_cache_key(recipe, region)
        if band_monitor is not None:
            from zaaggenz_dsp.band_router import BAND_NAMES, FILTER_POLICY
            if (authoritative or type(band_monitor) is not tuple or len(band_monitor) != 2
                    or type(band_monitor[0]) is not str or band_monitor[0] not in BAND_NAMES
                    or type(band_monitor[1]) is not str or band_monitor[1] not in ('solo', 'mute')
                    or region != render_region(recipe, None)):
                raise JobError('band monitor requires a full non-authoritative render and valid band/mode')
            rack = recipe.to_dict().get('rack')
            if rack is None or rack['crossovers']['method'] != FILTER_POLICY:
                raise JobError('band monitor requires a supported installed rack')
            tm = recipe.to_dict()['time_map']
            frames = beat_to_sample(tm, recipe.to_dict()['phrase']['end_beat']) - beat_to_sample(tm, '0/1')
            # Account for all zero-phase filter/intermediate float64 buffers
            # beyond the full processed render before job admission.
            estimate += frames * 128
            if estimate > self.scheduler.limits.max_job_memory_bytes:
                raise JobError('post-master band monitor exceeds job memory bound')
            key = digest({'domain':'zaaggenz.post-master-band-monitor-v1',
                          'full_key':key, 'band':band_monitor[0], 'mode':band_monitor[1],
                          'filter_method':FILTER_POLICY,
                          'crossovers_hz':rack['crossovers']['frequencies_hz']})
        request_key = digest({'domain':'zaaggenz.timeline-owned-request-v1',
                              'owner':self._cache_namespace, 'revision':revision,
                              'recipe':recipe.sha256, 'cache_key':key, 'authoritative':authoritative})
        if band_monitor is None:
            canonical = region_executor(recipe, revision, region)
        else:
            complete = make_render_executor(recipe, MelodicRenderSpec(), revision)
            selected_band, monitor_mode = band_monitor
            crossovers = tuple(recipe.to_dict()['rack']['crossovers']['frequencies_hz'])
            def canonical(ctx):
                original = complete(ctx)
                return _post_master_band_monitor(original, selected_band, monitor_mode,
                                                 crossovers, key, ctx)
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

    def submit_dry_monitor(self, data):
        """Render a detached dry comparison without changing the working project.

        A/B uses the existing bounded scheduler, per-session generation and
        exact-artifact guards. Only the current validated processed revision
        may request a source-bound comparison.
        """
        document = TimelineDocument(data)
        project = Project.from_document(document.to_dict()['project'])
        if project.rack is None:
            raise JobError('raw/dry monitoring requires an installed rack')
        with self._jobs_lock:
            if document.revision_id != self.session.current_revision_id():
                raise JobError('raw/dry monitoring requires the current Compose revision')
            project.reset_rack()
            proposal = document.to_dict()
            proposal['project'] = project.to_document()
            dry_document = TimelineDocument(proposal)
            result = self.submit(dry_document.to_dict(), region=None,
                                 name='Raw/dry A/B monitoring', authoritative=False)
            return {**result, 'monitor_source_revision_id': document.revision_id,
                    'monitor_policy': 'non-authoritative dry; no export slot'}

    def submit_band_monitor(self, data, band, mode):
        """Only a detached, exact-current full phrase may be band-monitored."""
        from zaaggenz_dsp.band_router import BAND_NAMES
        if type(band) is not str or band not in BAND_NAMES:
            raise JobError('unknown monitoring band')
        if type(mode) is not str or mode not in ('solo', 'mute'):
            raise JobError('unknown band-monitor mode')
        document = TimelineDocument(data)
        if Project.from_document(document.to_dict()['project']).rack is None:
            raise JobError('band monitoring requires an installed rack')
        with self._jobs_lock:
            if document.revision_id != self.session.current_revision_id():
                raise JobError('band monitoring requires the current Compose revision')
            result = self.submit(document.to_dict(), region=None,
                name='Post-master '+band+' '+mode+' monitor',
                authoritative=False, band_monitor=(band, mode))
            return {**result, 'monitor_source_revision_id':document.revision_id,
                    'monitor_policy':'non-authoritative post-master band; no export slot',
                    'monitor_band':band, 'monitor_mode':mode}

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
