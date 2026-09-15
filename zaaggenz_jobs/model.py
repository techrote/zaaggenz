from __future__ import annotations
from dataclasses import dataclass,field
from enum import IntEnum, Enum
import hashlib,json,math,os,re,tempfile,threading
from pathlib import Path
from copy import deepcopy
from zaaggenz_contracts import validate

HEX64=re.compile(r'^[0-9a-f]{64}$')
PRODUCTS={'synth','arrange','arrange_bass','bass','preview','analysis','research','batch'}

class JobError(RuntimeError): pass
class JobCancelled(JobError): pass

class JobClass(IntEnum):
    PREVIEW=0
    RENDER=10
    ANALYSIS=20
    RESEARCH=30
    BATCH=40

    @property
    def interactive(self): return self in (JobClass.PREVIEW,JobClass.RENDER)

class JobState(str,Enum):
    QUEUED='queued';RUNNING='running';CANCEL_REQUESTED='cancel_requested'
    CANCELLED='cancelled';COMPLETED='completed';FAILED='failed'

    @property
    def terminal(self): return self in (JobState.CANCELLED,JobState.COMPLETED,JobState.FAILED)

@dataclass(frozen=True)
class SchedulerLimits:
    interactive_workers:int=1
    background_workers:int=2
    max_queued_jobs:int=64
    max_background_queued_jobs:int=48
    max_history_jobs:int=2048
    max_memory_bytes:int=512*1024*1024
    interactive_memory_reserve_bytes:int=64*1024*1024
    max_job_memory_bytes:int=256*1024*1024
    max_preview_memory_bytes:int=64*1024*1024
    preview_cache_bytes:int=96*1024*1024
    preview_cache_entries:int=32
    numeric_threads:int=1
    def __post_init__(self):
        ints=(self.interactive_workers,self.background_workers,self.max_queued_jobs,
              self.max_background_queued_jobs,self.max_history_jobs,self.max_memory_bytes,
              self.interactive_memory_reserve_bytes,self.max_job_memory_bytes,
              self.max_preview_memory_bytes,self.preview_cache_bytes,self.preview_cache_entries,
              self.numeric_threads)
        if any(type(v)is not int or v<0 for v in ints): raise JobError('scheduler limits must be non-negative integers')
        if self.interactive_workers<1 or self.background_workers<1: raise JobError('both scheduler lanes require at least one worker')
        if self.max_queued_jobs<1 or self.max_history_jobs<16: raise JobError('queue/history bounds are too small')
        if self.max_background_queued_jobs>self.max_queued_jobs: raise JobError('background queue bound exceeds total queue bound')
        if self.max_history_jobs<self.max_queued_jobs+self.interactive_workers+self.background_workers:
            raise JobError('history bound must hold the maximum queued plus running jobs')
        if not 0<self.interactive_memory_reserve_bytes<=self.max_memory_bytes: raise JobError('invalid interactive memory reserve')
        if not 0<self.max_preview_memory_bytes<=self.interactive_memory_reserve_bytes: raise JobError('preview bound exceeds reserved interactive memory')
        if not 0<self.max_job_memory_bytes<=self.max_memory_bytes: raise JobError('job memory bound exceeds process reservation')
        if not 1<=self.numeric_threads<=8: raise JobError('numeric thread bound must be 1..8')

class CancellationToken:
    def __init__(self): self._event=threading.Event()
    @property
    def cancelled(self): return self._event.is_set()
    def cancel(self): self._event.set()
    def check(self):
        if self.cancelled: raise JobCancelled('job cancelled')

@dataclass(frozen=True)
class JobContext:
    job_id:str
    token:CancellationToken
    _progress:object
    def check_cancelled(self): self.token.check()
    def progress(self,value): self._progress(value)

@dataclass(frozen=True)
class JobSnapshot:
    job_id:str;job_class:str;state:str;revision_id:str;generation:int
    progress:float;estimated_memory_bytes:int;submitted_sequence:int
    cache_hit:bool;cancel_requested:bool;error:str|None


def _sha(value,name):
    if type(value)is not str or not HEX64.fullmatch(value): raise JobError(f'{name} must be a lowercase SHA-256')


def _json_snapshot(value,name='scopes'):
    """Return one immutable canonical byte snapshot of bounded JSON metadata."""
    try:
        text=json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':'))
    except (TypeError,ValueError) as exc: raise JobError(f'{name} must be bounded JSON metadata') from exc
    payload=text.encode('utf-8')
    if len(payload)>2_000_000: raise JobError(f'{name} metadata too large')
    return payload


def _json_restore(payload):
    # json.loads always creates fresh mutable containers, so callers cannot obtain
    # a reference to the validated canonical snapshot held by RenderArtifact.
    return json.loads(payload.decode('utf-8'))


@dataclass(frozen=True,init=False)
class RenderArtifact:
    revision_id:str
    recipe_sha256:str
    product:str
    cache_key:str
    audio_bytes:bytes
    _asset_json:bytes=field(repr=False)
    _scopes_json:bytes=field(repr=False)

    def __init__(self,revision_id,recipe_sha256,product,cache_key,audio_bytes,asset,scopes):
        for value,name in ((revision_id,'revision_id'),(recipe_sha256,'recipe_sha256'),(cache_key,'cache_key')):_sha(value,name)
        if product not in PRODUCTS: raise JobError('unknown render product')
        if not isinstance(audio_bytes,bytes): raise JobError('audio payload must be immutable bytes')
        if len(audio_bytes)>512*1024*1024: raise JobError('audio payload exceeds artifact bound')
        try: validate(asset,'AudioAssetRef')
        except Exception as exc: raise JobError('invalid audio asset metadata') from exc
        asset_copy=deepcopy(asset)
        if asset_copy['identity_domain']=='pcm-f32le-interleaved-v1':
            expected=asset_copy['frame_count']*asset_copy['channels']*4
            if len(audio_bytes)!=expected: raise JobError('PCM artifact byte length disagrees with frame/channel metadata')
        if asset_copy['content_sha256']!=hashlib.sha256(audio_bytes).hexdigest():
            raise JobError('audio bytes do not match declared content identity')
        asset_json=_json_snapshot(asset_copy,'asset');scopes_json=_json_snapshot(scopes,'scopes')
        object.__setattr__(self,'revision_id',revision_id);object.__setattr__(self,'recipe_sha256',recipe_sha256)
        object.__setattr__(self,'product',product);object.__setattr__(self,'cache_key',cache_key)
        object.__setattr__(self,'audio_bytes',audio_bytes);object.__setattr__(self,'_asset_json',asset_json)
        object.__setattr__(self,'_scopes_json',scopes_json)

    @property
    def asset(self): return _json_restore(self._asset_json)
    @property
    def scopes(self): return _json_restore(self._scopes_json)
    @property
    def cache_bytes(self):
        # Count actual immutable audio plus serialized public metadata rather than an arbitrary slab estimate.
        return len(self.audio_bytes)+len(json.dumps(self.metadata(),ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8'))
    def metadata(self):
        return dict(revision_id=self.revision_id,recipe_sha256=self.recipe_sha256,product=self.product,
                    cache_key=self.cache_key,asset=self.asset,scopes=self.scopes)


def atomic_publish_bytes(path,payload,token=None):
    """Publish only a complete validated byte payload; cancellation never replaces the destination."""
    if not isinstance(payload,(bytes,bytearray)): raise JobError('payload must be bytes')
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=path.name+'.',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f:
            f.write(bytes(payload));f.flush();os.fsync(f.fileno())
        if token is not None: token.check()
        os.replace(tmp,path)
    finally:
        try: os.unlink(tmp)
        except FileNotFoundError: pass
    return path


def numeric_thread_limit(limit=1):
    """Apply an explicit process-wide native threadpool cap when threadpoolctl is installed."""
    if type(limit)is not int or not 1<=limit<=8: raise JobError('numeric thread limit must be 1..8')
    for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','VECLIB_MAXIMUM_THREADS'):
        os.environ[name]=str(limit)
    try:
        from threadpoolctl import threadpool_limits
    except ImportError:
        return None
    return threadpool_limits(limits=limit)
