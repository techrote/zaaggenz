from __future__ import annotations
from dataclasses import asdict,replace
from copy import deepcopy
import hashlib,io,math,threading
import numpy as np
from scipy.io import wavfile
from zaaggenz_components import analyse_components
from zaaggenz_jobs import JobClass,JobError,JobScheduler,RenderArtifact,SchedulerLimits
from zaaggenz_spectral import ChordnessRequest,apply_chordness,harmonic_comb
from zaaggenz_tuning import IntervalGrid,dissonance_curve,harmonic_spectrum
from .model import InspectorError,SlotIdentity,compatibility_rows,slot_identity,snapshot_from_chordness

SONORITIES={'major-third':5/4,'fourth':4/3,'fifth':3/2,'minor-sixth':8/5}
DEFAULT_CONTROLS={'amount':.72,'root_hz':220.,'sonority':'fifth','anchor':'source'}

def validate_controls(value):
    if value is None:value=DEFAULT_CONTROLS
    if type(value)is not dict:raise InspectorError('controls must be an object')
    allowed={'amount','root_hz','sonority','anchor'}
    if set(value)-allowed:raise InspectorError('unknown inspector control')
    out={**DEFAULT_CONTROLS,**value}
    for name in ('amount','root_hz'):
        if type(out[name]) not in (int,float) or type(out[name]) is bool or not math.isfinite(float(out[name])):raise InspectorError(name+' must be finite')
        out[name]=float(out[name])
    if not 0<=out['amount']<=1:raise InspectorError('amount must be in [0,1]')
    if not 120<=out['root_hz']<=420:raise InspectorError('root_hz must be in [120,420]')
    if out['sonority'] not in SONORITIES:raise InspectorError('unknown sonority')
    if out['anchor'] not in ('source','upper','both'):raise InspectorError('anchor must be source, upper or both')
    return out

def fixture_source(sample_rate_hz,*,variant=0):
    if type(sample_rate_hz)is not int or not 8000<=sample_rate_hz<=192000:raise InspectorError('sample rate out of range')
    n=round(sample_rate_hz*1.25);t=np.arange(n,dtype=np.float64)/sample_rate_hz;root=220.;upper=330.;x=np.zeros(n,dtype=np.float64)
    for group,base in enumerate((root,upper)):
        for harmonic in range(1,8):
            detune=(3.5 if group else -2.0)*(harmonic/7.)
            hz=base*harmonic*2**(detune/1200.)
            amp=(.24 if group==0 else .16)/(harmonic**.78)
            phase=.19*harmonic+.31*group+.07*variant
            x+=amp*np.sin(2*np.pi*hz*t+phase)
    x+=.035*np.sin(2*np.pi*(713.+variant*11.)*t+.43)
    env=np.minimum(1.,t/.018)*np.exp(-.13*t);x*=env
    click=min(n-1,round(.035*sample_rate_hz));x[click]+=.22
    peak=float(np.max(np.abs(x),initial=1e-12));x*=.72/max(peak,1e-12)
    return x.astype(np.float32)

def build_analysis(source,sample_rate_hz,controls,*,revision_seed=None,before_identity=None,source_binding=None,checkpoint=None,progress=None):
    controls=validate_controls(controls);src=np.asarray(source,dtype=np.float32)
    if src.ndim!=1 or len(src)<64 or not np.isfinite(src).all():raise InspectorError('finite mono source required')
    if checkpoint:checkpoint()
    if progress:progress(.05)
    analysis=analyse_components(src,sample_rate_hz)
    if checkpoint:checkpoint()
    ratio=SONORITIES[controls['sonority']];root=controls['root_hz'];upper=root*ratio;max_hz=min(sample_rate_hz*.45,7000.)
    templates=(harmonic_comb('comb.root',root,harmonics=8,max_hz=max_hz,tooth_capacity=2,label='Root comb'),
               harmonic_comb('comb.upper',upper,harmonics=8,max_hz=max_hz,tooth_capacity=2,label=controls['sonority'].replace('-',' ').title()+' comb'))
    amount=controls['amount'];selected=('comb.root','comb.upper')
    request=ChordnessRequest(templates,mode='hybrid',selection_mode='manual',selected_template_ids=selected,max_selected_templates=2,
        retune_amount=amount,reweight_amount=min(1.,amount*.72),min_confidence=.42,tolerance_cents=42.,max_assignment_cents=700.,
        max_displacement_cents=180.,max_correction_slew_cents_per_second=2600.,max_gain_db=4.5,max_gain_slew_db_per_second=28.,preserve_ambiguous=True)
    if progress:progress(.18)
    result=apply_chordness(analysis,request,checkpoint=checkpoint,progress=(None if progress is None else lambda x:progress(.18+.62*x)))
    if checkpoint:checkpoint()
    lower=harmonic_spectrum('compat.root',root,partials=8);upper_spec=harmonic_spectrum('compat.upper',upper,partials=8)
    curve=dissonance_curve(lower,upper_spec,IntervalGrid(0.,1200.,20.))
    snapshot=snapshot_from_chordness(result,src,result.audio,sample_rate_hz,controls=controls,compatibility=compatibility_rows(curve),revision_seed=revision_seed,before_identity=before_identity)
    if source_binding is not None:
        provenance=deepcopy(source_binding)
        snapshot=replace(snapshot,expert={**snapshot.expert,'source_binding':provenance})
    if progress:progress(1.)
    return {'source':src.copy(),'after':np.asarray(result.audio,dtype=np.float32).copy(),'snapshot':snapshot}

def _wav(audio,sample_rate_hz):
    buffer=io.BytesIO();wavfile.write(buffer,sample_rate_hz,np.asarray(audio,dtype=np.float32));return buffer.getvalue()

def _rms(audio):
    a=np.asarray(audio,dtype=np.float64);return float(np.sqrt(np.mean(a*a))) if len(a) else 0.

class InspectorService:
    def __init__(self,sample_rate_hz=12000,*,demo_fixture=False,scheduler=None,current_revision_provider=None):
        if type(sample_rate_hz)is not int or not 8000<=sample_rate_hz<=192000:raise InspectorError('sample rate out of range')
        if scheduler is not None and not isinstance(scheduler,JobScheduler):raise InspectorError('scheduler must be a JobScheduler')
        if current_revision_provider is not None and not callable(current_revision_provider):raise InspectorError('current_revision_provider must be callable')
        self.sample_rate_hz=sample_rate_hz;self._owns_scheduler=scheduler is None
        self.scheduler=JobScheduler(SchedulerLimits(interactive_workers=1,background_workers=1,max_queued_jobs=8,max_background_queued_jobs=4,max_history_jobs=16)) if scheduler is None else scheduler
        self._current_revision_provider=current_revision_provider;self._closed=False
        self._lock=threading.RLock();self._jobs={};self._published=set();self._history=[];self._frozen=None
        self._source=None;self._source_bytes=None;self._source_identity=None;self._source_binding=None;self._after=None;self._snapshot=None;self._working=None
        if demo_fixture:self.bind_demo_fixture(0,analyse=True)
    @property
    def owns_scheduler(self):return self._owns_scheduler
    def close(self):
        if self._closed:return
        self._closed=True
        if self._owns_scheduler:self.scheduler.shutdown(cancel=True,timeout=5)
    def _authoritative_revision(self):
        return None if self._current_revision_provider is None else self._current_revision_provider()
    def _authority_stale(self,binding=None):
        binding=self._source_binding if binding is None else binding
        if self._current_revision_provider is None or not binding or binding.get('kind')!='render-artifact-v1':return False
        return self._authoritative_revision()!=binding.get('revision_id')
    def _stale(self):
        return self._snapshot is not None and (self._snapshot.before.revision_id!=self.source_identity.revision_id or self._authority_stale())
    @property
    def source_identity(self):
        if self._source_identity is None:raise InspectorError('no inspector source is bound')
        return self._source_identity
    @property
    def after_identity(self):
        if self._snapshot is None:raise InspectorError('no analysed B slot is available')
        return self._snapshot.after
    def _clear_analysis_for_source(self,source,source_bytes,identity,binding,sample_rate_hz):
        self.sample_rate_hz=int(sample_rate_hz);self._source=source;self._source_bytes=source_bytes;self._source_identity=identity;self._source_binding=deepcopy(binding)
        self._after=None;self._snapshot=None;self._working=identity;self._history.clear();self._frozen=None
    def bind_artifact(self,artifact):
        if not isinstance(artifact,RenderArtifact):raise InspectorError('RenderArtifact required for production inspector binding')
        asset=artifact.asset
        if asset.get('identity_domain')!='pcm-f32le-interleaved-v1':raise InspectorError('inspector requires pcm-f32le-interleaved-v1 audio')
        if asset.get('channels')!=1 or asset.get('channel_layout')!='mono':raise InspectorError('inspector requires mono render audio')
        frames=asset.get('frame_count');sample_rate=asset.get('sample_rate_hz')
        if type(frames)is not int or frames<64:raise InspectorError('inspector source must contain at least 64 frames')
        if type(sample_rate)is not int or not 8000<=sample_rate<=192000:raise InspectorError('sample rate out of range')
        content=hashlib.sha256(artifact.audio_bytes).hexdigest()
        if content!=asset.get('content_sha256'):raise InspectorError('render artifact content identity mismatch')
        source=np.frombuffer(artifact.audio_bytes,dtype='<f4')
        if len(source)!=frames or not np.isfinite(source).all():raise InspectorError('finite mono render audio required')
        binding={'kind':'render-artifact-v1','revision_id':artifact.revision_id,'recipe_sha256':artifact.recipe_sha256,'cache_key':artifact.cache_key,
                 'product':artifact.product,'content_sha256':content,'identity_domain':asset['identity_domain'],'sample_rate_hz':sample_rate,
                 'channels':1,'frame_count':frames}
        identity=SlotIdentity('A',artifact.revision_id,content,sample_rate,frames,'Before · bound render artifact',_rms(source),float(np.max(np.abs(source),initial=0.)))
        with self._lock:
            self._clear_analysis_for_source(source,artifact.audio_bytes,identity,binding,sample_rate)
            return self.state()
    def bind_demo_fixture(self,variant=0,*,analyse=True):
        """Explicit deterministic demo/test source. Production callers should bind RenderArtifact."""
        if type(variant)is not int:raise InspectorError('fixture variant must be an integer')
        source=fixture_source(self.sample_rate_hz,variant=variant);seed='initial' if variant==0 else f'test-{variant}'
        if analyse:
            initial=build_analysis(source,self.sample_rate_hz,DEFAULT_CONTROLS,revision_seed=seed)
            source=np.asarray(initial['source'],dtype=np.float32);source_bytes=source.astype('<f4',copy=False).tobytes();identity=initial['snapshot'].before
            binding={'kind':'demo-fixture','variant':variant,'revision_id':identity.revision_id,'content_sha256':identity.audio_sha256,'sample_rate_hz':self.sample_rate_hz,'frame_count':len(source)}
            with self._lock:
                self._source=np.frombuffer(source_bytes,dtype='<f4');self._source_bytes=source_bytes;self._source_identity=identity;self._source_binding=binding
                self._after=np.asarray(initial['after'],dtype=np.float32);self._snapshot=initial['snapshot'];self._working=identity;self._history.clear();self._frozen=None
                return self.state()
        source_bytes=source.astype('<f4',copy=False).tobytes();source_view=np.frombuffer(source_bytes,dtype='<f4');identity=slot_identity('A',source_view,self.sample_rate_hz,'Before · source',revision_seed=seed)
        binding={'kind':'demo-fixture','variant':variant,'revision_id':identity.revision_id,'content_sha256':identity.audio_sha256,'sample_rate_hz':self.sample_rate_hz,'frame_count':len(source_view)}
        with self._lock:
            self._clear_analysis_for_source(source_view,source_bytes,identity,binding,self.sample_rate_hz)
            return self.state()
    def compensation(self):
        if self._source is None or self._after is None:return None
        a=np.asarray(self._source,dtype=np.float64);b=np.asarray(self._after,dtype=np.float64);ra=float(np.sqrt(np.mean(a*a)));rb=float(np.sqrt(np.mean(b*b)));raw=ra/max(rb,1e-12);peak=float(np.max(np.abs(b),initial=0.));safe=(.98/max(peak,1e-12)) if peak>0 else raw;gain=min(raw,safe)
        return {'gain_linear':float(gain),'gain_db':float(20*math.log10(max(gain,1e-12))),'target_rms':ra,'source_rms':rb,'peak_limited':bool(safe<raw)}
    def state(self):
        with self._lock:
            authority=self._authoritative_revision()
            policy={'analysis_auto_apply':False,'apply_requires_explicit_action':True,'stale_result_rejected':True,'normalization':'none','production_source_requires_artifact_binding':True,'fixture_requires_explicit_demo':True,'authoritative_compose_revision_guard':self._current_revision_provider is not None}
            if self._source_identity is None:
                return {'method':'zg.harmonic_comb_inspector.v1','bound':False,'source_binding':None,'source_stale':False,'authoritative_revision_id':authority,'slots':{'A':None,'B':None},'snapshot':None,'snapshot_stale':False,
                        'frozen_snapshot_id':None,'working':None,'undo_depth':0,'compensation':None,'policy':policy}
            return {'method':'zg.harmonic_comb_inspector.v1','bound':True,'source_binding':deepcopy(self._source_binding),'source_stale':self._authority_stale(),'authoritative_revision_id':authority,
                    'slots':{'A':self.source_identity.to_dict(),'B':None if self._snapshot is None else self.after_identity.to_dict()},
                    'snapshot':None if self._snapshot is None else self._snapshot.to_dict(),'snapshot_stale':self._stale(),
                    'frozen_snapshot_id':None if self._frozen is None else self._frozen.snapshot_id,'working':self._working.to_dict(),
                    'undo_depth':len(self._history),'compensation':self.compensation(),'policy':policy}
    def audio(self,slot,*,compensated=False):
        if slot not in ('A','B'):raise InspectorError('slot must be A or B')
        with self._lock:
            if self._source is None:raise InspectorError('no inspector source is bound')
            if slot=='B' and self._after is None:raise InspectorError('no analysed B slot is available')
            audio=self._source if slot=='A' else self._after
            if compensated and slot=='B':audio=np.asarray(audio,dtype=np.float64)*self.compensation()['gain_linear']
            return _wav(audio,self.sample_rate_hz),self.source_identity.revision_id if slot=='A' else self.after_identity.revision_id
    def submit_analysis(self,controls):
        controls=validate_controls(controls)
        with self._lock:
            if self._source is None:raise InspectorError('bind an immutable render artifact before analysis')
            if self._authority_stale():raise InspectorError('bound inspector source is stale relative to authoritative Compose revision')
            source=self._source.copy();expected=self.source_identity;sample_rate=self.sample_rate_hz;binding=deepcopy(self._source_binding)
        def execute(ctx):
            ctx.check_cancelled();return build_analysis(source,sample_rate,controls,before_identity=expected,source_binding=binding,checkpoint=ctx.check_cancelled,progress=ctx.progress)
        jid=self.scheduler.submit(JobClass.ANALYSIS,expected.revision_id,execute,estimated_memory_bytes=max(8*1024*1024,int(source.nbytes*48)))
        with self._lock:self._jobs[jid]={'expected_revision_id':expected.revision_id,'expected_source_binding':deepcopy(binding),'controls':deepcopy(controls)}
        return {'job_id':jid,'expected_revision_id':expected.revision_id,'controls':controls}
    def _job_meta(self,job_id):
        with self._lock:
            meta=self._jobs.get(job_id)
            if meta is None:raise JobError('unknown inspector job')
            return deepcopy(meta)
    def cancel(self,job_id):
        self._job_meta(job_id)
        return self.scheduler.cancel(job_id)
    def status(self,job_id):
        meta=self._job_meta(job_id);snapshot=self.scheduler.snapshot(job_id);response=asdict(snapshot)
        if snapshot.state!='completed':return response
        with self._lock:
            current_revision=self.source_identity.revision_id;current_binding=deepcopy(self._source_binding);authority=self._authoritative_revision()
            authority_stale=self._current_revision_provider is not None and meta['expected_source_binding'].get('kind')=='render-artifact-v1' and authority!=meta['expected_revision_id']
            if current_revision!=meta['expected_revision_id'] or current_binding!=meta['expected_source_binding'] or authority_stale:
                return {**response,'published':False,'stale':True,'expected_revision_id':meta['expected_revision_id'],'current_revision_id':current_revision,'authoritative_revision_id':authority,
                        'expected_source_binding':deepcopy(meta['expected_source_binding']),'current_source_binding':current_binding}
            if job_id in self._published:return {**response,'published':True,'stale':False,'state_payload':self.state()}
            result=self.scheduler.result(job_id)
            self._after=np.asarray(result['after'],dtype=np.float32);self._snapshot=result['snapshot'];self._published.add(job_id)
            return {**response,'published':True,'stale':False,'state_payload':self.state()}
    def freeze(self,snapshot_id):
        with self._lock:
            if self._snapshot is None or snapshot_id!=self._snapshot.snapshot_id:raise InspectorError('snapshot is not current')
            if self._stale():raise InspectorError('cannot freeze stale snapshot')
            self._frozen=self._snapshot;return {'frozen_snapshot_id':snapshot_id}
    def apply(self,snapshot_id):
        with self._lock:
            candidate=self._snapshot if self._snapshot is not None and snapshot_id==self._snapshot.snapshot_id else self._frozen if self._frozen and snapshot_id==self._frozen.snapshot_id else None
            if candidate is None:raise InspectorError('unknown snapshot')
            if candidate.before.revision_id!=self.source_identity.revision_id:raise InspectorError('cannot apply transform to different source revision')
            if self._current_revision_provider is not None and self._source_binding.get('kind')=='render-artifact-v1' and candidate.before.revision_id!=self._authoritative_revision():raise InspectorError('cannot apply transform to stale authoritative Compose revision')
            self._history.append(self._working);self._working=candidate.after
            return {'working':self._working.to_dict(),'undo_depth':len(self._history),'applied_snapshot_id':candidate.snapshot_id}
    def undo(self):
        with self._lock:
            if not self._history:raise InspectorError('nothing to undo')
            self._working=self._history.pop();return {'working':self._working.to_dict(),'undo_depth':len(self._history)}
    def replace_source_for_test(self,variant=1):
        """Test-only explicit fixture rebinding hook; production uses bind_artifact()."""
        self.bind_demo_fixture(int(variant),analyse=False)
        return self.source_identity