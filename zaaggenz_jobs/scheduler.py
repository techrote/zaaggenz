from __future__ import annotations
from collections import OrderedDict
from dataclasses import dataclass
import hashlib,heapq,math,os,threading,time
from .model import (JobClass,JobState,SchedulerLimits,JobError,JobCancelled,
                    CancellationToken,JobContext,JobSnapshot,RenderArtifact)
from .numeric_runtime import numeric_thread_limit

@dataclass
class _Record:
    job_id:str;job_class:JobClass;revision_id:str;generation:int;estimated_memory_bytes:int
    sequence:int;executor:object;dedupe_key:str|None;token:CancellationToken
    state:JobState=JobState.QUEUED;progress:float=0.;result:object=None;error:str|None=None
    cache_hit:bool=False;submitted_at:float=0.;started_at:float|None=None;finished_at:float|None=None

class _ResultCache:
    def __init__(self,max_bytes,max_entries):
        self.max_bytes=max_bytes;self.max_entries=max_entries;self.bytes=0;self.data=OrderedDict()
    def get(self,key):
        item=self.data.pop(key,None)
        if item is None:return None
        self.data[key]=item;return item[0]
    def put(self,key,value):
        if not isinstance(value,RenderArtifact):return
        size=value.cache_bytes
        old=self.data.pop(key,None)
        if old:self.bytes-=old[1]
        if size>self.max_bytes:return
        self.data[key]=(value,size);self.bytes+=size
        while self.bytes>self.max_bytes or len(self.data)>self.max_entries:
            _,(_,n)=self.data.popitem(last=False);self.bytes-=n

class JobScheduler:
    """Two-lane bounded local scheduler.

    Background work can consume only max_memory-reserve and can never occupy the
    interactive worker lane. A PREVIEW must fit inside the reserve. This gives a
    mechanical non-starvation guarantee against long analysis/batch jobs without
    pretending arbitrary non-cooperative renders are preemptible.
    """
    def __init__(self,limits=SchedulerLimits(),*,apply_numeric_limit=True):
        if not isinstance(limits,SchedulerLimits):raise JobError('SchedulerLimits required')
        self.limits=limits;self._cv=threading.Condition();self._seq=0;self._records={};self._order=[]
        self._interactive=[];self._background=[];self._active_dedupe={};self._running_i=0;self._running_b=0
        self._shutdown=False;self._cache=_ResultCache(limits.preview_cache_bytes,limits.preview_cache_entries)
        self._numeric_guard=numeric_thread_limit(limits.numeric_threads) if apply_numeric_limit else None
        self._threads=[]
        try:
            for lane,count in (('interactive',limits.interactive_workers),('background',limits.background_workers)):
                for i in range(count):
                    t=threading.Thread(target=self._worker,args=(lane,),name=f'zaaggenz-{lane}-{i}',daemon=True)
                    t.start();self._threads.append(t)
        except BaseException:
            with self._cv:
                self._shutdown=True;self._cv.notify_all()
            deadline=time.monotonic()+1.0
            for t in self._threads:t.join(max(0.0,deadline-time.monotonic()))
            if self._numeric_guard is not None:self._numeric_guard.restore_original_limits()
            raise
    def _new_id(self):
        self._seq+=1
        raw=f'{time.time_ns()}:{self._seq}:'.encode()+os.urandom(16)
        return hashlib.sha256(raw).hexdigest()[:32]
    def _hex64(self,value,name):
        if type(value)is not str or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):raise JobError(f'invalid {name}')
    def _lane_memory_capacity(self,job_class):
        return (self.limits.max_memory_bytes if job_class.interactive else
                self.limits.max_memory_bytes-self.limits.interactive_memory_reserve_bytes)
    def submit(self,job_class,revision_id,executor,*,estimated_memory_bytes,generation=0,dedupe_key=None):
        try:job_class=JobClass(job_class)
        except (TypeError,ValueError) as exc:raise JobError('unknown job class') from exc
        self._hex64(revision_id,'revision id')
        if not callable(executor):raise JobError('executor must be callable')
        if type(estimated_memory_bytes)is not int or not 0<=estimated_memory_bytes<=self.limits.max_job_memory_bytes:raise JobError('invalid job memory estimate')
        if job_class is JobClass.PREVIEW and estimated_memory_bytes>self.limits.max_preview_memory_bytes:raise JobError('preview exceeds reserved memory bound')
        lane='interactive' if job_class.interactive else 'background'
        if estimated_memory_bytes>self._lane_memory_capacity(job_class):
            raise JobError(f'job memory estimate exceeds permanent {lane} lane capacity')
        if type(generation)is not int or not 0<=generation<=2**53-1:raise JobError('invalid generation')
        if dedupe_key is not None and (type(dedupe_key)is not str or not 1<=len(dedupe_key)<=256):raise JobError('invalid dedupe key')
        with self._cv:
            if self._shutdown:raise JobError('scheduler is shutting down')
            if job_class is JobClass.PREVIEW and dedupe_key:
                active=self._active_dedupe.get(dedupe_key)
                if active:
                    state=self._records[active].state
                    if state in (JobState.QUEUED,JobState.RUNNING):return active
            queued=sum(r.state is JobState.QUEUED for r in self._records.values())
            if queued>=self.limits.max_queued_jobs:raise JobError('scheduler queue full')
            if not job_class.interactive:
                bg=sum(r.state is JobState.QUEUED and not r.job_class.interactive for r in self._records.values())
                if bg>=self.limits.max_background_queued_jobs:raise JobError('background queue full')
            jid=self._new_id();rec=_Record(jid,job_class,revision_id,generation,estimated_memory_bytes,self._seq,
                                         executor,dedupe_key,CancellationToken(),submitted_at=time.monotonic())
            self._records[jid]=rec;self._order.append(jid)
            heap=(self._interactive if job_class.interactive else self._background)
            heapq.heappush(heap,(int(job_class),rec.sequence,jid))
            if job_class is JobClass.PREVIEW and dedupe_key:self._active_dedupe[dedupe_key]=jid
            self._trim_history();self._cv.notify_all();return jid
    def cached_preview(self,dedupe_key):
        if type(dedupe_key)is not str:return None
        with self._cv:return self._cache.get(dedupe_key)
    def _trim_history(self):
        if len(self._records)<=self.limits.max_history_jobs:return
        kept=[]
        for jid in self._order:
            rec=self._records.get(jid)
            if rec is None:continue
            if len(self._records)>self.limits.max_history_jobs and rec.state.terminal:
                self._records.pop(jid,None);continue
            kept.append(jid)
        self._order=kept
    def _can_start(self,rec,lane):
        total=self._running_i+self._running_b
        if lane=='background':
            return (self._running_b+rec.estimated_memory_bytes<=self.limits.max_memory_bytes-self.limits.interactive_memory_reserve_bytes
                    and total+rec.estimated_memory_bytes<=self.limits.max_memory_bytes)
        return total+rec.estimated_memory_bytes<=self.limits.max_memory_bytes
    def _pop_startable(self,lane):
        heap=self._interactive if lane=='interactive' else self._background
        held=[];chosen=None
        while heap:
            item=heapq.heappop(heap);rec=self._records.get(item[2])
            if rec is None or rec.state is not JobState.QUEUED:continue
            if self._can_start(rec,lane):chosen=rec;break
            held.append(item)
        for item in held:heapq.heappush(heap,item)
        return chosen
    def _commit_completion_locked(self,rec,result):
        if rec.token.cancelled or rec.state is JobState.CANCEL_REQUESTED:
            rec.result=None;rec.state=JobState.CANCELLED;rec.finished_at=time.monotonic();return False
        rec.result=result;rec.progress=1.;rec.state=JobState.COMPLETED;rec.finished_at=time.monotonic()
        if rec.job_class is JobClass.PREVIEW and rec.dedupe_key:self._cache.put(rec.dedupe_key,result)
        return True
    def _worker(self,lane):
        while True:
            with self._cv:
                while True:
                    if self._shutdown and not any(r.state is JobState.QUEUED and r.job_class.interactive==(lane=='interactive') for r in self._records.values()):return
                    rec=self._pop_startable(lane)
                    if rec:break
                    self._cv.wait(.1)
                if rec.token.cancelled:
                    rec.state=JobState.CANCELLED;rec.finished_at=time.monotonic();self._finish_dedupe(rec);self._cv.notify_all();continue
                rec.state=JobState.RUNNING;rec.started_at=time.monotonic()
                if lane=='interactive':self._running_i+=rec.estimated_memory_bytes
                else:self._running_b+=rec.estimated_memory_bytes
            def progress(value):
                if type(value) not in (int,float) or not math.isfinite(float(value)) or not 0<=float(value)<=1:raise JobError('progress must be finite in [0,1]')
                with self._cv:
                    if float(value)<rec.progress:raise JobError('progress cannot go backwards')
                    rec.progress=float(value);self._cv.notify_all()
            try:
                ctx=JobContext(rec.job_id,rec.token,progress);result=rec.executor(ctx);rec.token.check()
                with self._cv:self._commit_completion_locked(rec,result)
            except JobCancelled:
                with self._cv:rec.state=JobState.CANCELLED;rec.result=None;rec.finished_at=time.monotonic()
            except Exception as exc:
                with self._cv:rec.state=JobState.FAILED;rec.result=None;rec.error=f'{type(exc).__name__}: {str(exc)[:512]}';rec.finished_at=time.monotonic()
            finally:
                with self._cv:
                    if rec.finished_at is None:rec.finished_at=time.monotonic()
                    if lane=='interactive':self._running_i-=rec.estimated_memory_bytes
                    else:self._running_b-=rec.estimated_memory_bytes
                    self._finish_dedupe(rec);self._cv.notify_all()
    def _finish_dedupe(self,rec):
        if rec.dedupe_key and self._active_dedupe.get(rec.dedupe_key)==rec.job_id:self._active_dedupe.pop(rec.dedupe_key,None)
    def cancel(self,job_id):
        with self._cv:
            rec=self._records.get(job_id)
            if rec is None:raise JobError('unknown job id')
            if rec.state.terminal:return False
            rec.token.cancel()
            if rec.state is JobState.QUEUED:
                rec.state=JobState.CANCELLED;rec.finished_at=time.monotonic();self._finish_dedupe(rec)
            elif rec.state is JobState.RUNNING:rec.state=JobState.CANCEL_REQUESTED
            self._cv.notify_all();return True
    def snapshot(self,job_id):
        with self._cv:
            rec=self._records.get(job_id)
            if rec is None:raise JobError('unknown job id')
            return JobSnapshot(rec.job_id,rec.job_class.name.lower(),rec.state.value,rec.revision_id,rec.generation,
                               rec.progress,rec.estimated_memory_bytes,rec.sequence,rec.cache_hit,rec.token.cancelled,rec.error)
    def wait(self,job_id,timeout=None):
        deadline=None if timeout is None else time.monotonic()+timeout
        with self._cv:
            while True:
                snap=self.snapshot(job_id)
                if JobState(snap.state).terminal:return snap
                remain=None if deadline is None else deadline-time.monotonic()
                if remain is not None and remain<=0:return snap
                self._cv.wait(remain)
    def result(self,job_id):
        with self._cv:
            rec=self._records.get(job_id)
            if rec is None:raise JobError('unknown job id')
            if rec.state is not JobState.COMPLETED:raise JobError('job has no completed result')
            return rec.result
    def shutdown(self,*,cancel=True,timeout=5.0):
        with self._cv:
            self._shutdown=True
            if cancel:
                for rec in self._records.values():
                    if not rec.state.terminal:
                        rec.token.cancel()
                        if rec.state is JobState.QUEUED:
                            rec.state=JobState.CANCELLED;rec.finished_at=time.monotonic();self._finish_dedupe(rec)
                        elif rec.state is JobState.RUNNING:rec.state=JobState.CANCEL_REQUESTED
            self._cv.notify_all()
        deadline=time.monotonic()+timeout
        for t in self._threads:t.join(max(0,deadline-time.monotonic()))
        alive=any(t.is_alive() for t in self._threads)
        guard=self._numeric_guard
        if not alive and guard is not None and hasattr(guard,'restore_original_limits'):guard.restore_original_limits()
        return not alive
