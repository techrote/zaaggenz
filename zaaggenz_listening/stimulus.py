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
    def __init__(self,max_bytes=256*1024*1024):self.max_bytes=max_bytes;self._stimuli={};self._raw={};self._playback={};self._lock=threading.Lock()
    def add_artifact(self,name,artifact,*,start_frame=0,end_frame=None):
        stimulus,raw=freeze_artifact(name,artifact,start_frame=start_frame,end_frame=end_frame)
        with self._lock:
            if sum(len(v) for v in self._raw.values())+len(raw)>self.max_bytes:raise ListeningError('listening audio store budget exceeded')
            self._stimuli[stimulus.to_dict()['id']]=stimulus;self._raw[stimulus.to_dict()['id']]=raw
        return stimulus
    def stimulus(self,sid):
        with self._lock:
            if sid not in self._stimuli:raise ListeningError('stimulus audio is missing; exact material will not be silently regenerated')
            return self._stimuli[sid]
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
                staged_playback.setdefault(psha,(pcm,s['sample_rate_hz'],s['channels']));matched.append(deepcopy(manifest))
            projected=sum(len(v) for v in self._raw.values())+sum(len(v[0]) for v in self._playback.values())+sum(len(v[0]) for k,v in staged_playback.items() if k not in self._playback)
            if projected>self.max_bytes:raise ListeningError('matched playback store budget exceeded')
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
