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

    def archive_material(self, stimuli, matched_rows):
        """Snapshot exact raw/matched bytes for a single immutable trial archive."""
        if type(stimuli) is not list or type(matched_rows) is not list:
            raise ListeningError('archive material requires stimulus and match lists')
        docs=[]
        for stimulus in stimuli:
            if not isinstance(stimulus,Stimulus):raise ListeningError('archive material requires Stimulus objects')
            docs.append(stimulus.to_dict())
        by_id={d['id']:d for d in docs}
        if len(by_id)!=len(docs) or len(matched_rows)!=len(docs) or set(by_id)!={r.get('stimulus_id') for r in matched_rows if type(r)is dict}:
            raise ListeningError('archive material does not exactly match trial stimuli')
        raw_rows=[];playback_rows=[];blobs={}
        with self._lock:
            for sid in sorted(by_id):
                d=by_id[sid]
                existing=self._stimuli.get(sid)
                if existing is None or existing.to_dict()!=d or sid not in self._raw:
                    raise ListeningError('archive raw stimulus bytes are missing')
                raw=self._raw[sid];rsha=hashlib.sha256(raw).hexdigest()
                if rsha!=d['raw_pcm_sha256']:raise ListeningError('archive raw stimulus hash mismatch')
                expected=d['frame_count']*d['channels']*4
                if len(raw)!=expected:raise ListeningError('archive raw stimulus shape mismatch')
                prior=blobs.get(rsha)
                if prior is not None and prior!=raw:raise ListeningError('archive SHA collision with different raw bytes')
                blobs.setdefault(rsha,raw)
                raw_rows.append({'stimulus_id':sid,'sha256':rsha,'byte_length':len(raw),'sample_rate_hz':d['sample_rate_hz'],'channels':d['channels'],'frame_count':d['frame_count']})
            for row in sorted(matched_rows,key=lambda r:r['stimulus_id']):
                sid=row['stimulus_id'];psha=row['playback_sha256'];d=by_id[sid]
                if psha not in self._playback:raise ListeningError('archive matched playback bytes are missing')
                pcm,sr,ch=self._playback[psha]
                if (sr,ch)!=(d['sample_rate_hz'],d['channels']) or len(pcm)!=d['frame_count']*ch*4:
                    raise ListeningError('archive playback shape mismatch')
                if hashlib.sha256(pcm).hexdigest()!=psha:raise ListeningError('archive playback hash mismatch')
                prior=blobs.get(psha)
                if prior is not None and prior!=pcm:raise ListeningError('archive SHA collision with different playback bytes')
                blobs.setdefault(psha,pcm)
                playback_rows.append({'stimulus_id':sid,'sha256':psha,'byte_length':len(pcm),'sample_rate_hz':sr,'channels':ch,'frame_count':d['frame_count']})
        return {'raw_material':raw_rows,'playback_material':playback_rows,'blobs':blobs}

    def install_archive_material(self, stimuli, matched_rows, raw_material, playback_material, blobs):
        """Validate and atomically install exact archive PCM; return rollback receipt."""
        if type(stimuli) is not list or not all(isinstance(s,Stimulus) for s in stimuli):
            raise ListeningError('archive install requires Stimulus objects')
        if type(matched_rows) is not list or type(raw_material) is not list or type(playback_material) is not list or type(blobs) is not dict:
            raise ListeningError('invalid archive material indexes')
        docs={s.to_dict()['id']:s.to_dict() for s in stimuli}
        if len(docs)!=len(stimuli):raise ListeningError('archive contains duplicate stimulus identities')
        matches={r['stimulus_id']:r for r in matched_rows}
        if len(matches)!=len(matched_rows) or set(matches)!=set(docs):raise ListeningError('archive matched rows do not cover exact stimulus set')
        raw_by={r['stimulus_id']:r for r in raw_material}
        playback_by={r['stimulus_id']:r for r in playback_material}
        if len(raw_by)!=len(raw_material) or len(playback_by)!=len(playback_material) or set(raw_by)!=set(docs) or set(playback_by)!=set(docs):
            raise ListeningError('archive material indexes do not cover exact stimulus set')
        staged_raw={};staged_playback={}
        for sid,d in docs.items():
            rr=raw_by[sid];rsha=rr['sha256'];raw=blobs.get(rsha)
            if raw is None or hashlib.sha256(raw).hexdigest()!=rsha or rsha!=d['raw_pcm_sha256']:
                raise ListeningError('archive raw bytes do not match stimulus provenance')
            shape=(d['sample_rate_hz'],d['channels'],d['frame_count'])
            if (rr['sample_rate_hz'],rr['channels'],rr['frame_count'])!=shape or len(raw)!=d['frame_count']*d['channels']*4:
                raise ListeningError('archive raw bytes do not match stimulus shape')
            if not np.all(np.isfinite(np.frombuffer(raw,dtype='<f4'))):raise ListeningError('archive raw PCM must be finite')
            staged_raw[sid]=raw
            pr=playback_by[sid];expected_sha=matches[sid]['playback_sha256'];psha=pr['sha256'];pcm=blobs.get(psha)
            if pcm is None or psha!=expected_sha or hashlib.sha256(pcm).hexdigest()!=psha:
                raise ListeningError('archive playback bytes do not match trial provenance')
            if (pr['sample_rate_hz'],pr['channels'],pr['frame_count'])!=shape or len(pcm)!=d['frame_count']*d['channels']*4:
                raise ListeningError('archive playback bytes do not match stimulus shape')
            if not np.all(np.isfinite(np.frombuffer(pcm,dtype='<f4'))):raise ListeningError('archive playback PCM must be finite')
            payload=(pcm,d['sample_rate_hz'],d['channels'])
            prior=staged_playback.get(psha)
            if prior is not None and prior!=payload:raise ListeningError('archive deduplicated playback metadata conflict')
            staged_playback[psha]=payload
        receipt={'stimuli':set(),'raw':set(),'playback':set()}
        with self._lock:
            additional=0
            for stimulus in stimuli:
                sid=stimulus.to_dict()['id'];existing=self._stimuli.get(sid)
                if existing is not None and existing.to_dict()!=stimulus.to_dict():raise ListeningError('archive stimulus identity collision')
                current=self._raw.get(sid)
                if current is not None and current!=staged_raw[sid]:raise ListeningError('archive raw stimulus collision')
                if current is None:additional+=len(staged_raw[sid])
            for psha,payload in staged_playback.items():
                current=self._playback.get(psha)
                if current is not None and current!=payload:raise ListeningError('archive playback identity collision')
                if current is None:additional+=len(payload[0])
            self._require_capacity_locked(additional,'listening audio store budget exceeded by archive')
            for stimulus in stimuli:
                sid=stimulus.to_dict()['id']
                if sid not in self._stimuli:self._stimuli[sid]=stimulus;receipt['stimuli'].add(sid)
                if sid not in self._raw:self._raw[sid]=staged_raw[sid];receipt['raw'].add(sid)
            for psha,payload in staged_playback.items():
                if psha not in self._playback:self._playback[psha]=payload;receipt['playback'].add(psha)
        return receipt

    def rollback_archive_material(self, receipt):
        """Remove only material inserted by one failed archive transaction."""
        if type(receipt) is not dict:return
        with self._lock:
            for psha in receipt.get('playback',()):self._playback.pop(psha,None)
            for sid in receipt.get('raw',()):self._raw.pop(sid,None)
            for sid in receipt.get('stimuli',()):self._stimuli.pop(sid,None)
