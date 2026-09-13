"""Bounded offline renders; immutable full-phrase state precedes region extraction."""
from __future__ import annotations
from dataclasses import asdict
import hashlib
import io
import numpy as np
from scipy.io import wavfile
from zaaggenz_contracts import digest
from zaaggenz_contracts.music import beat_to_sample
from zaaggenz_jobs import JobScheduler, SchedulerLimits, JobClass, RenderArtifact, JobError
from zaaggenz_melody import MelodicRenderSpec, make_render_executor
from .model import TimelineDocument, compile_recipe, render_region, memory_estimate, text, describe


def region_executor(recipe, revision, region):
    """Render the full phrase, then crop: tails crossing the selection start remain."""
    full_executor = make_render_executor(recipe, MelodicRenderSpec(), revision)
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
        key = digest({'domain': 'zaaggenz.timeline-region-v1', 'full_cache_key': full.cache_key, 'region': region})
        ctx.check_cancelled()
        return RenderArtifact(revision, recipe.sha256, 'synth', key, pcm, asset, scopes)
    return execute


class TimelineService:
    def __init__(self):
        self.scheduler = JobScheduler(SchedulerLimits(interactive_workers=1, background_workers=1,
                                                      max_queued_jobs=8, max_background_queued_jobs=4,
                                                      max_history_jobs=16))

    def validate(self, data):
        document = TimelineDocument(data)
        recipe = compile_recipe(document)
        return {**describe(document), 'recipe_sha256': recipe.sha256,
                'estimated_memory_bytes': memory_estimate(recipe)}

    def submit(self, data, region=None, name='Render'):
        text(name, 'render name')
        document = TimelineDocument(data)
        recipe = compile_recipe(document)
        region = render_region(recipe, region)
        estimate = memory_estimate(recipe)  # always full cost, not just selected length
        job_id = self.scheduler.submit(JobClass.RENDER, document.revision_id,
                                        region_executor(recipe, document.revision_id, region),
                                        estimated_memory_bytes=estimate)
        return {'job_id': job_id, 'revision_id': document.revision_id, 'recipe_sha256': recipe.sha256,
                'region': region, 'name': name}

    def status(self, job_id):
        snapshot = self.scheduler.snapshot(job_id)
        response = asdict(snapshot)
        if snapshot.state == 'completed':
            response['artifact'] = self.scheduler.result(job_id).metadata()
        return response

    def wave(self, job_id):
        result = self.scheduler.result(job_id)
        if not isinstance(result, RenderArtifact):
            raise JobError('audio is not available')
        buffer = io.BytesIO()
        wavfile.write(buffer, result.asset['sample_rate_hz'], np.frombuffer(result.audio_bytes, dtype='<f4'))
        return buffer.getvalue(), result.revision_id

    def close(self):
        self.scheduler.shutdown(cancel=True, timeout=5)
