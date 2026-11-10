"""Opt-in, source-bound Compose -> controlled Nyquismic PCM bridge.

This adapter operates only on a completed *full* ordinary Compose render owned
by its current RuntimeSession. It does not install a graph node, a band insert,
a final 48-kHz delivery converter or an upstream feature tap. Caller packet
SHA strings alone never authenticate Compose authority.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
import hashlib
import numpy as np

from zaaggenz_contracts import digest
from zaaggenz_contracts.nyquismic import SonicSpec, EvaluationPolicy
from zaaggenz_dsp.nyquismic import FrozenInput, SamplerPlan
from zaaggenz_jobs import JobError
from zaaggenz_timeline.model import compile_recipe, render_region
from zaaggenz_timeline.service import TimelineService


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise JobError('controlled Compose binding: ' + message)


@dataclass(frozen=True, init=False)
class ComposeControlledSource:
    """Current-session witness for immutable full-mix PCM, not a graph capability."""
    timeline: TimelineService
    job_id: str
    generation: int
    timeline_revision_id: str
    recipe_sha256: str
    rack_revision_sha256: str
    source: FrozenInput

    def __init__(self, *args, **kwargs):
        _require(False, 'Compose source must come from a real owned render')

    def _guard(self) -> None:
        session = self.timeline.session
        _require(session.current_identity() ==
                 (self.generation, self.timeline_revision_id),
                 'stale/ABA Compose session generation or revision')
        _require(self.timeline.status(self.job_id).get('accepted') is True,
                 'render is not the accepted current owned Compose artifact')
        document = session.document()
        recipe = compile_recipe(document)
        _require(document.revision_id == self.timeline_revision_id and
                 recipe.sha256 == self.recipe_sha256,
                 'compiled Compose recipe no longer matches the captured source')
        artifact = self.timeline.artifact(self.job_id)
        _require(artifact.product == 'synth' and
                 artifact.revision_id == self.timeline_revision_id and
                 artifact.recipe_sha256 == self.recipe_sha256,
                 'owned render no longer matches source identity')
        _require(artifact.asset['sample_rate_hz'] == self.source.sample_rate_hz and
                 artifact.asset['channels'] == self.source.asset.to_dict()['channels'] and
                 artifact.asset['frame_count'] == self.source.asset.to_dict()['frame_count'] and
                 artifact.asset['content_sha256'] == self.source.asset.to_dict()['content_sha256'] and
                 artifact.audio_bytes == self.source.pcm.astype('<f4', copy=False).tobytes(),
                 'source was not captured from current owned Compose PCM')
        _require(self.rack_revision_sha256 == digest({
            'domain': 'nyq.compose-rack-bound-v1', 'rack': recipe.to_dict().get('rack')
        }), 'source rack identity differs from compiled Compose recipe')

    @property
    def packet_claims(self) -> dict[str, str]:
        """Recipe and source receipts for the #267 producer; not proof on their own."""
        self._guard()
        return {
            'input_asset_sha256': self.source.asset.sha256,
            'source_revision_sha256': self.timeline_revision_id,
            'graph_revision_sha256': self.recipe_sha256,
            'expected_live_graph_sha256': self.recipe_sha256,
            'rack_revision_sha256': self.rack_revision_sha256,
        }

    def prepare(self, sonic: SonicSpec, packet, evaluation: EvaluationPolicy,
                *, frame_count=None, cancelled=None):
        """Re-admit the packet using actual source/session state; authored routes only."""
        _require(cancelled is None or callable(cancelled), 'invalid cancellation hook')
        self._guard()
        _require(all(r.source_kind == 'authored' for r in packet.route_receipts),
                 'upstream feature PCM/graph taps are not authenticated here')
        _require(sonic.channels == self.source.asset.to_dict()['channels'],
                 'controlled channel count differs from Compose PCM')
        def obsolete():
            return (cancelled is not None and cancelled()) or (
                self.timeline.session.current_identity() !=
                (self.generation, self.timeline_revision_id))
        if frame_count is None:
            # A compiled packet declares its full *physical* extent. The
            # SamplerPlan default instead derives an extent from input length;
            # that is not necessarily the intended controlled-clock region.
            # Never silently truncate a non-grid-aligned packet.
            from fractions import Fraction
            physical_frames = (
                Fraction(packet.full_end_s) - Fraction(sonic.clock.origin_s)
            ) * evaluation.evaluation_rate_hz
            _require(physical_frames.denominator == 1 and
                     physical_frames.numerator > 0,
                     'packet full physical extent does not fit evaluation grid')
            frame_count = physical_frames.numerator
        plan = SamplerPlan.prepare(
            self.source, sonic, evaluation,
            controlled_clock=packet,
            frame_count=frame_count,
            source_revision_sha256=self.timeline_revision_id,
            graph_revision_sha256=self.recipe_sha256,
            rack_revision_sha256=self.rack_revision_sha256,
            context_sha256=digest({
                'domain': 'nyq.compose-source-bound-context.v1',
                'timeline_revision': self.timeline_revision_id,
                'recipe': self.recipe_sha256,
                'source': self.source.asset.sha256,
                'packet': packet.sha256,
            }),
            cancelled=obsolete,
        )
        self._guard()
        handle = object.__new__(ComposeControlledRender)
        object.__setattr__(handle, 'source_binding', self)
        object.__setattr__(handle, '_plan', plan)
        return handle


@dataclass(frozen=True, init=False)
class ComposeControlledRender:
    """Restrict publication to the same real session generation and owned job."""
    source_binding: ComposeControlledSource
    _plan: object

    def __init__(self, *args, **kwargs):
        _require(False, 'controlled render must be prepared from authenticated Compose')

    @property
    def render_sha256(self):
        self.source_binding._guard()
        return self._plan.render_sha256

    def checkpoint(self, frame: int):
        self.source_binding._guard()
        result = self._plan.checkpoint(frame)
        self.source_binding._guard()
        return result

    def render(self, start_frame=None, stop_frame=None, *, checkpoint=None,
               cancelled=None, progress=None):
        _require(cancelled is None or callable(cancelled), 'invalid cancellation hook')
        _require(progress is None or callable(progress), 'invalid progress hook')
        binding = self.source_binding
        binding._guard()
        def obsolete():
            return (cancelled is not None and cancelled()) or (
                binding.timeline.session.current_identity() !=
                (binding.generation, binding.timeline_revision_id))
        result = self._plan.render(start_frame, stop_frame, checkpoint=checkpoint,
                                   cancelled=obsolete, progress=progress)
        binding._guard()  # Never publish audio/checkpoints across edit or cancellation.
        return result


def bind_completed_compose(timeline: TimelineService, job_id: str) -> ComposeControlledSource:
    """Authenticate bytes against the live full-phrase Compose session and job.

    This is a deliberately non-default post-Compose *full-mix* tap. Only the
    TimelineService's owned completed job, not a supplied graph SHA or a
    caller-created RenderArtifact, may supply audio.
    """
    _require(type(timeline) is TimelineService, 'TimelineService is required')
    generation, revision = timeline.session.current_identity()
    _require(timeline.status(job_id).get('accepted') is True,
             'job is not current, completed and owned')
    document = timeline.session.document()
    recipe = compile_recipe(document)
    artifact = timeline.artifact(job_id)
    _require(artifact.product == 'synth' and artifact.revision_id == revision and
             artifact.recipe_sha256 == recipe.sha256,
             'artifact revision/compiled graph does not match session')
    _require(artifact.scopes.get('region') == render_region(recipe, None),
             'region render is not an authorized full-context PCM source')
    asset = artifact.asset
    _require(asset.get('channels') in (1, 2) and
             asset.get('sample_rate_hz') in range(8000, 192001),
             'unsupported source channel/rate')
    pcm = artifact.audio_bytes
    _require(type(pcm) is bytes and
             len(pcm) == asset['frame_count'] * asset['channels'] * 4 and
             hashlib.sha256(pcm).hexdigest() == asset['content_sha256'],
             'source bytes or asset identity mismatch')
    frames = np.frombuffer(pcm, dtype='<f4')
    frames = frames if asset['channels'] == 1 else frames.reshape(-1, asset['channels'])
    source = FrozenInput.from_pcm(frames, asset['sample_rate_hz'])
    rack_sha = digest({'domain': 'nyq.compose-rack-bound-v1',
                       'rack': recipe.to_dict().get('rack')})
    binding = object.__new__(ComposeControlledSource)
    for field, value in zip(fields(ComposeControlledSource), (
        timeline, job_id, generation, revision, recipe.sha256, rack_sha, source
    )):
        object.__setattr__(binding, field.name, value)
    binding._guard()
    return binding
