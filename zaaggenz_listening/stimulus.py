"""Freeze exact RenderArtifacts and create immutable level-matched playback bytes."""
from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass
import hashlib,io,json,math,threading
import numpy as np
from scipy.io import wavfile
from zaaggenz_contracts import digest
from zaaggenz_jobs import RenderArtifact
from .model import Stimulus,ListeningError,VERSION

def _db(x):return 20*math.log10(max(float(x),1e-30))
def _linear(db):return 10**(float(db)/20)
def _finite_dbfs(value,name):
    if type(value) not in (int,float) or type(value) is bool or not math.isfinite(float(value)):raise ListeningError(f'{name} must be a finite numeric dBFS value')
    return float(value)

def freeze_artifact(name,artifact,*,start_frame=0,end_frame=None):
    if not isinstance(artifact,RenderArtifact):raise ListeningError('completed RenderArtifact required')
    a=artifact.asset
    if a['identity_domain']!='pcm-f32le-interleaved-v1':raise ListeningError('only float32 PCM artifacts can be frozen')
    channels=a['channels'];frames=a['frame_count'];end_frame=frames if end_frame is None else end_frame
    if type(start_frame)is not int or type(end_frame)is not int or not 0<=start_frame<end_frame<=frames:raise ListeningError('invalid excerpt frames')
    x=np.frombuffer(artifact.audio_bytes,dtype='<f4').reshape(frames,channels)[start_frame:end_frame].copy();raw=x.astype('<f4',copy=False).tobytes();raw_sha=hashlib.sha256(raw).hexdigest()
    alignment={'artifact_region':deepcopy(artifact.scopes.get('region')),'artifact_offset_sample':artifact.scopes.get('offset_sample'),'excerpt_start_frame':start_frame,'excerpt_end_frame':end_frame}
    identity={'domain':'zaaggenz.listening-stimulus-v1','revision_id':artifact.revision_id,'recipe_sha256':artifact.recipe_sha256,'product':artifact.product,'cache_key':artifact.cache_key,'source_content_sha256':a['content_sha256'],'excerpt':{'start_frame':start_frame,'end_frame':end_frame},'raw_pcm_sha256':raw_sha}
    sid=digest(identity)
    doc={'format':'zaaggenz-listening-stimulus','version':VERSION,'id':sid,'name':name,'revision_id':artifact.revision_id,'recipe_sha256':artifact.recipe_sha256,'product':artifact.product,'cache_key':artifact.cache_key,'source_asset':{'content_sha256':a['content_sha256'],'identity_domain':a['identity_domain'],'sample_rate_hz':a['sample_rate_hz'],'channels':channels,'frame_count':frames},'excerpt':{'start_frame':start_frame,'end_frame':end_frame},'raw_pcm_sha256':raw_sha,'sample_rate_hz':a['sample_rate_hz'],'channels':channels,'frame_count':end_frame-start_frame,'alignment':alignment}
    return Stimulus(doc),raw

@dataclass(frozen=True)
class FrozenPlayback:
    manifest:dict
    pcm:bytes

class ListeningAudioStore:
    def __init__(self,max_bytes=256*1024*1024):
        if type(max_bytes)is not int or max_bytes<=0:raise ListeningError('listening audio store max_bytes must be a positive integer')
        self.max_bytes=max_bytes;self._stimuli={};self._raw={};self._playback={};self._lock=threading.Lock()
    def _accounting_locked(self):
        raw_bytes=sum(len(v) for v in self._raw.values());playback_bytes=sum(len(v[0]) for v in self._playback.values())
        return {'method':'retained-pcm-physical-bytes-v1','raw_entries':len(self._raw),'playback_entries':len(self._playback),'raw_pcm_bytes':raw_bytes,'playback_pcm_bytes':playback_bytes,'total_pcm_bytes':raw_bytes+playback_bytes,'max_bytes':self.max_bytes}
    def accounting(self):
        """Return physical retained-PCM accounting; playback hashes are counted once."""
        with self._lock:return dict(self._accounting_locked())
    def _require_capacity_locked(self,additional_bytes,message):
        if type(additional_bytes)is not int or additional_bytes<0:raise ListeningError('invalid listening audio store budget projection')
        projected=self._accounting_locked()['total_pcm_bytes']+additional_bytes
        if projected>self.max_bytes:raise ListeningError(message)
        return projected
    def add_artifact(self,name,artifact,*,start_frame=0,end_frame=None):
        stimulus,raw=freeze_artifact(name,artifact,start_frame=start_frame,end_frame=end_frame);sid=stimulus.to_dict()['id']
        with self._lock:
            existing=self._raw.get(sid)
            if existing is not None and existing!=raw:raise ListeningError('stimulus identity collision with different retained PCM')
            self._require_capacity_locked(0 if existing is not None else len(raw),'listening audio store budget exceeded')
            self._stimuli[sid]=stimulus;self._raw[sid]=raw
        return stimulus
    def stimulus(self,sid):
        with self._lock:
            if sid not in self._stimuli:raise ListeningError('stimulus audio is missing; exact material will not be silently regenerated')
            return self._stimuli[sid]
    def raw_pcm(self,sid):
        """Return an immutable copy of one frozen source excerpt for trusted archival export."""
        with self._lock:
            if sid not in self._stimuli or sid not in self._raw:raise ListeningError('stimulus audio is missing; exact material will not be silently regenerated')
            return bytes(self._raw[sid])
    def playback_record(self,playback_sha):
        """Return exact matched PCM plus its immutable shape metadata for trusted archival export."""
        with self._lock:
            if playback_sha not in self._playback:raise ListeningError('matched playback missing')
            pcm,sr,ch=self._playback[playback_sha]
            return bytes(pcm),sr,ch
    def restore_archive(self,stimuli,raw_by_stimulus,playback_by_sha):
        """Atomically admit already-verified archive bytes without rerendering or rematching."""
        if type(stimuli)is not list or not stimuli or any(not isinstance(s,Stimulus) for s in stimuli):raise ListeningError('archive restore requires validated stimuli')
        if type(raw_by_stimulus)is not dict or type(playback_by_sha)is not dict:raise ListeningError('archive restore requires exact audio maps')
        docs=[s.to_dict() for s in stimuli];sids=[d['id'] for d in docs]
        if len(set(sids))!=len(sids) or set(raw_by_stimulus)!=set(sids):raise ListeningError('archive raw audio coverage does not match stimuli')
        staged_raw={};staged_playback={}
        for stimulus,d in zip(stimuli,docs):
            sid=d['id'];raw=raw_by_stimulus[sid]
            if type(raw)is not bytes:raise ListeningError('archive raw PCM must be bytes')
            expected=d['frame_count']*d['channels']*4
            if len(raw)!=expected or hashlib.sha256(raw).hexdigest()!=d['raw_pcm_sha256']:raise ListeningError('archive raw PCM identity/shape mismatch')
            staged_raw[sid]=(stimulus,raw)
        for psha,payload in playback_by_sha.items():
            if type(psha)is not str or len(psha)!=64 or any(c not in '0123456789abcdef' for c in psha):raise ListeningError('archive playback SHA-256 is invalid')
            if type(payload)is not tuple or len(payload)!=3:raise ListeningError('archive playback record is invalid')
            pcm,sr,ch=payload
            if type(pcm)is not bytes or type(sr)is not int or type(ch)is not int or sr<=0 or ch<=0:raise ListeningError('archive playback record is invalid')
            if hashlib.sha256(pcm).hexdigest()!=psha:raise ListeningError('archive playback PCM hash mismatch')
            staged_playback[psha]=(pcm,sr,ch)
        with self._lock:
            additional=0
            for sid,(stimulus,raw) in staged_raw.items():
                existing_stimulus=self._stimuli.get(sid);existing_raw=self._raw.get(sid)
                if existing_stimulus is not None and existing_stimulus.to_dict()!=stimulus.to_dict():raise ListeningError('stimulus identity collision with different archive provenance')
                if existing_raw is not None and existing_raw!=raw:raise ListeningError('stimulus identity collision with different retained PCM')
                if existing_raw is None:additional+=len(raw)
            for psha,payload in staged_playback.items():
                existing=self._playback.get(psha)
                if existing is not None and existing!=payload:raise ListeningError('playback identity collision with different retained PCM metadata')
                if existing is None:additional+=len(payload[0])
            self._require_capacity_locked(additional,'listening audio store budget exceeded while reopening archive')
            for sid,(stimulus,raw) in staged_raw.items():
                self._stimuli.setdefault(sid,stimulus);self._raw.setdefault(sid,raw)
            for psha,payload in staged_playback.items():self._playback.setdefault(psha,payload)
        return self.accounting()
    def match(self,stimulus_ids,*,target_rms_dbfs=None,peak_ceiling_dbfs=-3.0):
        if type(stimulus_ids)is not list or not 2<=len(stimulus_ids)<=8 or len(set(stimulus_ids))!=len(stimulus_ids):raise ListeningError('2..8 unique stimulus IDs required')
        peak_ceiling_dbfs=_finite_dbfs(peak_ceiling_dbfs,'peak ceiling')
        if not -24<=peak_ceiling_dbfs<=-0.1:raise ListeningError('peak ceiling must be -24..-0.1 dBFS')
        requested_target_dbfs=None if target_rms_dbfs is None else _finite_dbfs(target_rms_dbfs,'RMS target')
        requested_target=None
        if requested_target_dbfs is not None:
            try:requested_target=_linear(requested_target_dbfs)
            except OverflowError as e:raise ListeningError('RMS target must convert to a finite positive linear amplitude') from e
            if not math.isfinite(requested_target) or requested_target<=0:raise ListeningError('RMS target must convert to a finite positive linear amplitude')
        rows=[];audio=[]
        with self._lock:
            for sid in stimulus_ids:
                if sid not in self._stimuli or sid not in self._raw:raise ListeningError('stimulus audio is missing; exact material will not be silently regenerated')
                s=self._stimuli[sid].to_dict();x=np.frombuffer(self._raw[sid],dtype='<f4').astype(np.float64)
                if not np.all(np.isfinite(x)):raise ListeningError('stimulus PCM must be finite for level matching')
                rms=float(np.sqrt(np.mean(x*x)));peak=float(np.max(np.abs(x),initial=0))
                if not math.isfinite(rms) or not math.isfinite(peak):raise ListeningError('stimulus level statistics must be finite for level matching')
                if rms<=1e-9 or peak<=1e-9:raise ListeningError('silent/near-silent material cannot be level matched')
                rows.append((sid,s,rms,peak));audio.append(x)
            ceiling=_linear(peak_ceiling_dbfs);max_targets=[rms*ceiling/peak for _,_,rms,peak in rows]
            target=min([rms for _,_,rms,_ in rows]+max_targets) if requested_target is None else requested_target
            if not math.isfinite(target) or target<=0:raise ListeningError('invalid RMS target')
            if any(target>limit+1e-12 for limit in max_targets):raise ListeningError('requested RMS target violates common sample-peak ceiling')
            matched=[];staged_playback={}
            for (sid,s,rms,peak),x in zip(rows,audio):
                gain=target/rms
                if not math.isfinite(gain) or gain<=0:raise ListeningError('derived level-match gain must be finite and positive')
                y=(x*gain).astype('<f4')
                if not np.all(np.isfinite(y)):raise ListeningError('derived level-matched PCM must be finite')
                yf64=y.astype(np.float64);m_rms=float(np.sqrt(np.mean(yf64*yf64)));m_peak=float(np.max(np.abs(y),initial=0))
                if not math.isfinite(m_rms) or not math.isfinite(m_peak):raise ListeningError('derived level-match statistics must be finite')
                pcm=y.tobytes();psha=hashlib.sha256(pcm).hexdigest()
                manifest={'stimulus_id':sid,'playback_sha256':psha,'gain_db':_db(gain),'source_rms_dbfs':_db(rms),'source_sample_peak':peak,'target_rms_dbfs':_db(target),'matched_rms_dbfs':_db(m_rms),'matched_sample_peak':m_peak,'sample_peak_headroom_db':-_db(m_peak),'method':'whole-file-rms-common-target-v1','true_peak_measured':False}
                numeric=('gain_db','source_rms_dbfs','source_sample_peak','target_rms_dbfs','matched_rms_dbfs','matched_sample_peak','sample_peak_headroom_db')
                if any(not math.isfinite(float(manifest[k])) for k in numeric):raise ListeningError('derived level-match metadata must be finite')
                payload=(pcm,s['sample_rate_hz'],s['channels']);existing=self._playback.get(psha)
                if existing is not None and existing!=payload:raise ListeningError('playback identity collision with different retained PCM metadata')
                staged_playback.setdefault(psha,payload);matched.append(deepcopy(manifest))
            additional=sum(len(v[0]) for k,v in staged_playback.items() if k not in self._playback)
            self._require_capacity_locked(additional,'matched playback store budget exceeded')
            for psha,payload in staged_playback.items():self._playback.setdefault(psha,payload)
            return matched
    def wav(self,playback_sha):
        with self._lock:
            if playback_sha not in self._playback:raise ListeningError('matched playback is missing; exact audio will not be silently regenerated')
            pcm,sr,ch=self._playback[playback_sha]
        x=np.frombuffer(pcm,dtype='<f4').reshape(-1,ch);b=io.BytesIO();wavfile.write(b,sr,x[:,0] if ch==1 else x);return b.getvalue()
    def playback_pcm(self,playback_sha):
        with self._lock:
            if playback_sha not in self._playback:raise ListeningError('matched playback missing')
            return bytes(self._playback[playback_sha][0])
    def has_playback(self,playback_sha):
        with self._lock:return playback_sha in self._playback
