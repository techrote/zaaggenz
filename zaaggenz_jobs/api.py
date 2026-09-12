from __future__ import annotations
from dataclasses import dataclass
import threading
from zaaggenz_contracts import digest
from .model import JobClass,JobState,JobError,RenderArtifact

@dataclass(frozen=True)
class RequestTicket:
    channel:str;generation:int;revision_id:str;job_id:str|None;dedupe_key:str;cache_hit:bool

class RenderCoordinator:
    """Revision/generation gate shared by HTTP handlers and browser transport semantics."""
    def __init__(self,scheduler):
        self.scheduler=scheduler;self._lock=threading.RLock();self._channels={}
    def _channel(self,value):
        if type(value)is not str or not value or len(value)>64 or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789_.-' for c in value):raise JobError('invalid channel')
    def _sha(self,value):
        if type(value)is not str or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):raise JobError('invalid revision/hash')
    def request_preview(self,channel,revision_id,recipe_sha256,cache_key,executor,*,estimated_memory_bytes):
        self._channel(channel);self._sha(revision_id);self._sha(recipe_sha256);self._sha(cache_key)
        dedupe=digest({'domain':'zaaggenz.preview-request-v1','revision_id':revision_id,
                       'recipe_sha256':recipe_sha256,'cache_key':cache_key})
        with self._lock:
            old=self._channels.get(channel);generation=(old['generation']+1 if old else 1)
            if old and old.get('job_id'):
                try:self.scheduler.cancel(old['job_id'])
                except JobError:pass
            cached=self.scheduler.cached_preview(dedupe)
            if cached is not None:
                if cached.revision_id!=revision_id or cached.recipe_sha256!=recipe_sha256 or cached.cache_key!=cache_key:raise JobError('preview cache identity mismatch')
                self._channels[channel]={'generation':generation,'revision_id':revision_id,'job_id':None,'artifact':cached}
                return RequestTicket(channel,generation,revision_id,None,dedupe,True)
            jid=self.scheduler.submit(JobClass.PREVIEW,revision_id,executor,estimated_memory_bytes=estimated_memory_bytes,
                                      generation=generation,dedupe_key=dedupe)
            self._channels[channel]={'generation':generation,'revision_id':revision_id,'job_id':jid,'artifact':None}
            return RequestTicket(channel,generation,revision_id,jid,dedupe,False)
    def poll(self,ticket):
        if not isinstance(ticket,RequestTicket):raise JobError('RequestTicket required')
        with self._lock:
            current=self._channels.get(ticket.channel)
            if current is None or current['generation']!=ticket.generation or current['revision_id']!=ticket.revision_id:
                return {'state':'stale','accepted':False,'generation':ticket.generation,'revision_id':ticket.revision_id}
            if ticket.cache_hit:
                artifact=current['artifact'];return self._accepted(ticket,artifact)
        snap=self.scheduler.snapshot(ticket.job_id)
        if snap.state==JobState.COMPLETED.value:
            artifact=self.scheduler.result(ticket.job_id)
            if not isinstance(artifact,RenderArtifact):raise JobError('preview executor returned non-render artifact')
            with self._lock:
                current=self._channels.get(ticket.channel)
                if current is None or current['generation']!=ticket.generation or current['revision_id']!=ticket.revision_id:
                    return {'state':'stale','accepted':False,'generation':ticket.generation,'revision_id':ticket.revision_id}
                if artifact.revision_id!=ticket.revision_id:raise JobError('audio result revision disagrees with request')
                current['artifact']=artifact
            return self._accepted(ticket,artifact)
        return {'state':snap.state,'accepted':False,'generation':ticket.generation,'revision_id':ticket.revision_id,
                'progress':snap.progress,'error':snap.error}
    def _accepted(self,ticket,artifact):
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
            self._channels[channel]={'generation':generation,'revision_id':None,'job_id':None,'artifact':None}
            return generation
    def close(self):
        with self._lock:
            for channel in tuple(self._channels):self.stop(channel)
        return self.scheduler.shutdown(cancel=True)
