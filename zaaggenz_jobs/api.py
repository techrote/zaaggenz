from __future__ import annotations
from dataclasses import dataclass
import threading
from zaaggenz_contracts import digest
from .model import JobClass,JobState,JobError,RenderArtifact

_PREVIEW_PRODUCT='preview'

@dataclass(frozen=True)
class RequestTicket:
    channel:str;generation:int;revision_id:str;job_id:str|None;dedupe_key:str;cache_hit:bool
    recipe_sha256:str='';cache_key:str='';product:str=_PREVIEW_PRODUCT

    @property
    def identity(self):
        return (self.revision_id,self.recipe_sha256,self.cache_key,self.product)

class RenderCoordinator:
    """Revision/generation gate shared by HTTP handlers and browser transport semantics."""
    def __init__(self,scheduler):
        self.scheduler=scheduler;self._lock=threading.RLock();self._channels={}
    def _channel(self,value):
        if type(value)is not str or not value or len(value)>64 or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789_.-' for c in value):raise JobError('invalid channel')
    def _sha(self,value):
        if type(value)is not str or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):raise JobError('invalid revision/hash')
    @staticmethod
    def _artifact_identity(artifact):
        return (artifact.revision_id,artifact.recipe_sha256,artifact.cache_key,artifact.product)
    @staticmethod
    def _validate_preview_artifact(expected,artifact):
        if not isinstance(artifact,RenderArtifact):raise JobError('preview executor returned non-render artifact')
        actual=RenderCoordinator._artifact_identity(artifact)
        if actual!=expected:
            fields=('revision_id','recipe_sha256','cache_key','product')
            mismatch=','.join(name for name,want,got in zip(fields,expected,actual) if want!=got)
            raise JobError(f'preview identity mismatch: {mismatch}')
        return artifact
    def request_preview(self,channel,revision_id,recipe_sha256,cache_key,executor,*,estimated_memory_bytes):
        self._channel(channel);self._sha(revision_id);self._sha(recipe_sha256);self._sha(cache_key)
        expected=(revision_id,recipe_sha256,cache_key,_PREVIEW_PRODUCT)
        dedupe=digest({'domain':'zaaggenz.preview-request-v1','revision_id':revision_id,
                       'recipe_sha256':recipe_sha256,'cache_key':cache_key})
        with self._lock:
            old=self._channels.get(channel);generation=(old['generation']+1 if old else 1)
            # Identical replacement should adopt a still-useful computation, not cancel and
            # immediately submit the same work again. The old client generation becomes stale.
            if old and old.get('job_id') and old.get('dedupe_key')==dedupe:
                try:snap=self.scheduler.snapshot(old['job_id'])
                except JobError:snap=None
                if snap is not None and snap.state in (JobState.QUEUED.value,JobState.RUNNING.value):
                    self._channels[channel]={'generation':generation,'revision_id':revision_id,
                                             'job_id':old['job_id'],'artifact':None,'dedupe_key':dedupe}
                    return RequestTicket(channel,generation,revision_id,old['job_id'],dedupe,False,
                                         recipe_sha256,cache_key,_PREVIEW_PRODUCT)
            if old and old.get('job_id'):
                try:self.scheduler.cancel(old['job_id'])
                except JobError:pass
            cached=self.scheduler.cached_preview(dedupe)
            if cached is not None:
                self._validate_preview_artifact(expected,cached)
                self._channels[channel]={'generation':generation,'revision_id':revision_id,'job_id':None,
                                         'artifact':cached,'dedupe_key':dedupe}
                return RequestTicket(channel,generation,revision_id,None,dedupe,True,
                                     recipe_sha256,cache_key,_PREVIEW_PRODUCT)
            def checked_executor(ctx):
                return self._validate_preview_artifact(expected,executor(ctx))
            jid=self.scheduler.submit(JobClass.PREVIEW,revision_id,checked_executor,estimated_memory_bytes=estimated_memory_bytes,
                                      generation=generation,dedupe_key=dedupe)
            self._channels[channel]={'generation':generation,'revision_id':revision_id,'job_id':jid,
                                     'artifact':None,'dedupe_key':dedupe}
            return RequestTicket(channel,generation,revision_id,jid,dedupe,False,
                                 recipe_sha256,cache_key,_PREVIEW_PRODUCT)
    def poll(self,ticket):
        if not isinstance(ticket,RequestTicket):raise JobError('RequestTicket required')
        with self._lock:
            current=self._channels.get(ticket.channel)
            if current is None or current['generation']!=ticket.generation or current['revision_id']!=ticket.revision_id:
                return {'state':'stale','accepted':False,'generation':ticket.generation,'revision_id':ticket.revision_id}
            if ticket.cache_hit:
                artifact=self._validate_preview_artifact(ticket.identity,current['artifact'])
                return self._accepted(ticket,artifact)
        snap=self.scheduler.snapshot(ticket.job_id)
        if snap.state==JobState.COMPLETED.value:
            artifact=self.scheduler.result(ticket.job_id)
            with self._lock:
                current=self._channels.get(ticket.channel)
                if current is None or current['generation']!=ticket.generation or current['revision_id']!=ticket.revision_id:
                    return {'state':'stale','accepted':False,'generation':ticket.generation,'revision_id':ticket.revision_id}
                artifact=self._validate_preview_artifact(ticket.identity,artifact)
                current['artifact']=artifact
            return self._accepted(ticket,artifact)
        if snap.state==JobState.FAILED.value and snap.error:
            prefix='JobError: '
            if snap.error.startswith(prefix) and snap.error[len(prefix):].startswith(('preview identity mismatch:','preview executor returned non-render artifact')):
                raise JobError(snap.error[len(prefix):])
        return {'state':snap.state,'accepted':False,'generation':ticket.generation,'revision_id':ticket.revision_id,
                'progress':snap.progress,'error':snap.error}
    def _accepted(self,ticket,artifact):
        artifact=self._validate_preview_artifact(ticket.identity,artifact)
        meta=artifact.metadata()
        return {'state':'completed','accepted':True,'generation':ticket.generation,'revision_id':ticket.revision_id,
                'audio':artifact.audio_bytes,'artifact':meta}
    def stop(self,channel):
        self._channel(channel)
        with self._lock:
            current=self._channels.get(channel);generation=(current['generation']+1 if current else 1)
            if current and current.get('job_id'):
                try:self.scheduler.cancel(current['job_id'])
                except JobError:pass
            self._channels[channel]={'generation':generation,'revision_id':None,'job_id':None,
                                     'artifact':None,'dedupe_key':None}
            return generation
    def close(self):
        with self._lock:
            for channel in tuple(self._channels):self.stop(channel)
        return self.scheduler.shutdown(cancel=True)
