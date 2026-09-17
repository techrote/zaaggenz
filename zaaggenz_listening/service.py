"""Local immutable listening material and trial/result registry."""
from __future__ import annotations
import base64
import binascii
from copy import deepcopy
import hashlib
import json
import secrets
from zaaggenz_contracts import digest
from zaaggenz_jobs import RenderArtifact,JobError
from .model import TrialManifest,TrialResult,Stimulus,ListeningError,exact,sha
from .stimulus import ListeningAudioStore
from .trial import make_trial,make_participant_trial,make_result,public_trial,public_result,INSTRUCTIONS

TRUSTED_BUNDLE_VERSION='2.0.0'
ARCHIVE_ENCODING='base64-pcm-f32le-interleaved-v1'
MAX_ARCHIVE_BLOBS=16
MAX_ARCHIVE_PCM_BYTES=64*1024*1024
MAX_ARCHIVE_METADATA_BYTES=8*1024*1024
MAX_ARCHIVE_RESULTS=4096
# 64 MiB binary PCM expands to <86 MiB base64. Metadata is capped separately.
MAX_ARCHIVE_JSON_BYTES=104*1024*1024


def _blob_descriptor(blob):
    return {k:deepcopy(v) for k,v in blob.items() if k!='data_base64'}


def _archive_envelope(bundle):
    audio=bundle['audio']
    return {
        'format':bundle['format'],
        'version':bundle['version'],
        'role':bundle['role'],
        'stimuli':deepcopy(bundle['stimuli']),
        'manifest':deepcopy(bundle['manifest']),
        'results':deepcopy(bundle['results']),
        'audio':{
            'encoding':audio['encoding'],
            'blob_count':audio['blob_count'],
            'pcm_bytes':audio['pcm_bytes'],
            'blobs':[_blob_descriptor(blob) for blob in audio['blobs']],
        },
    }


def _bundle_sha256(bundle):
    """Digest the archive metadata plus content hashes without re-copying base64 payloads."""
    return digest({'domain':'zaaggenz.listening-bundle-v2','bundle':_archive_envelope(bundle)})


def _metadata_size(bundle):
    return len(json.dumps(_archive_envelope(bundle),sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8'))


def _validate_stimulus_identity(d):
    identity={
        'domain':'zaaggenz.listening-stimulus-v1',
        'revision_id':d['revision_id'],
        'recipe_sha256':d['recipe_sha256'],
        'product':d['product'],
        'cache_key':d['cache_key'],
        'source_content_sha256':d['source_asset']['content_sha256'],
        'excerpt':deepcopy(d['excerpt']),
        'raw_pcm_sha256':d['raw_pcm_sha256'],
    }
    if d['id']!=digest(identity):raise ListeningError('listening stimulus identity does not match archived provenance')


def _archive_blob(kind,sha256_value,stimulus_ids,pcm,sample_rate_hz,channels,frame_count):
    if len(pcm)!=frame_count*channels*4 or hashlib.sha256(pcm).hexdigest()!=sha256_value:raise ListeningError('retained PCM identity/shape mismatch during archive export')
    return {
        'kind':kind,
        'sha256':sha256_value,
        'byte_length':len(pcm),
        'sample_rate_hz':sample_rate_hz,
        'channels':channels,
        'frame_count':frame_count,
        'stimulus_ids':sorted(stimulus_ids),
        'data_base64':base64.b64encode(pcm).decode('ascii'),
    }


class ListeningService:
    def __init__(self,timeline_service):
        self.timeline=timeline_service;self.audio=ListeningAudioStore();self.trials={};self.results={};self._participant_to_trusted={};self._trusted_to_participant={}
    def freeze_job(self,job_id,name,start_frame=0,end_frame=None):
        try:artifact=self.timeline.artifact(job_id)
        except JobError as e:raise ListeningError(str(e)) from e
        if not isinstance(artifact,RenderArtifact):raise ListeningError('completed render job required')
        stimulus=self.audio.add_artifact(name,artifact,start_frame=start_frame,end_frame=end_frame)
        return stimulus.to_dict()
    def match(self,stimulus_ids,target_rms_dbfs=None,peak_ceiling_dbfs=-3.):return self.audio.match(stimulus_ids,target_rms_dbfs=target_rms_dbfs,peak_ceiling_dbfs=peak_ceiling_dbfs)
    @staticmethod
    def _stimulus_metadata(stimuli):
        rows={}
        for stimulus in stimuli:
            if not isinstance(stimulus,Stimulus):raise ListeningError('Stimulus required for result timing validation')
            d=stimulus.to_dict();rows[d['id']]={'sample_rate_hz':d['sample_rate_hz'],'frame_count':d['frame_count']}
        return rows
    def _trial_stimulus_metadata(self,trial):
        td=trial.to_dict();return self._stimulus_metadata([self.audio.stimulus(row['stimulus_id']) for row in td['matched_stimuli']])
    @staticmethod
    def _validated_participant_id(participant_id):
        if type(participant_id)is not str or len(participant_id)!=64 or any(c not in '0123456789abcdef' for c in participant_id):raise ListeningError('participant trial ID must be lowercase SHA-256')
        return participant_id
    def _register_trial(self,trial,participant_id=None):
        if not isinstance(trial,TrialManifest):raise ListeningError('TrialManifest required')
        tid=trial.to_dict()['id']
        if tid in self._trusted_to_participant:pid=self._trusted_to_participant[tid]
        else:
            pid=secrets.token_hex(32) if participant_id is None else participant_id
            self._validated_participant_id(pid)
            if pid in self._participant_to_trusted and self._participant_to_trusted[pid]!=tid:raise ListeningError('participant trial ID collision')
        existing=self.trials.get(tid)
        if existing is not None and existing.to_dict()!=trial.to_dict():raise ListeningError('trusted trial identity collision')
        self.trials[tid]=trial;self._participant_to_trusted[pid]=tid;self._trusted_to_participant[tid]=pid
        return public_trial(trial,pid)
    def create_trial(self,title,design,matched_stimuli,seed='0',endpoints=('liking','sound_quality'),instruction_template=None):
        """Trusted/programmatic deterministic construction used by offline evidence and tests."""
        return self._register_trial(make_trial(title,design,matched_stimuli,seed=seed,endpoints=endpoints,instruction_template=instruction_template))
    def create_participant_trial(self,title,design,matched_stimuli,seed='0',endpoints=('liking','sound_quality'),instruction_template=None):
        """HTTP participant construction: ordering may use the visible seed; ABX truth never does."""
        hidden=None if design!='abx' else secrets.choice(('A','B'))
        trial=make_participant_trial(title,design,matched_stimuli,seed=seed,endpoints=endpoints,instruction_template=instruction_template,hidden_abx_truth=hidden)
        return self._register_trial(trial)
    def _trusted_id(self,trial_id,*,participant_only=False):
        if trial_id in self._participant_to_trusted:return self._participant_to_trusted[trial_id]
        if not participant_only and trial_id in self.trials:return trial_id
        raise ListeningError('unknown trial')
    def participant_manifest(self,participant_id):
        return self.trials[self._trusted_id(participant_id,participant_only=True)]
    def manifest(self,trial_id):
        return self.trials[self._trusted_id(trial_id)]
    def submit(self,trial_id,payload):
        tid=self._trusted_id(trial_id);trial=self.trials[tid];result=make_result(trial,stimulus_metadata=self._trial_stimulus_metadata(trial),**payload);self.results.setdefault(tid,[]).append(result);return {'result':result.to_dict(),'result_sha256':result.sha256}
    def submit_participant(self,participant_id,payload):
        """One terminal participant response per public trial; retakes require a new trial."""
        tid=self._trusted_id(participant_id,participant_only=True);trial=self.trials[tid]
        if self.results.get(tid):raise ListeningError('participant trial already has a terminal result; create a new trial for a retake')
        result=make_result(trial,stimulus_metadata=self._trial_stimulus_metadata(trial),**payload);self.results.setdefault(tid,[]).append(result);view=public_result(result,participant_id)
        return {'result':view,'result_sha256':digest({'domain':'zaaggenz.listening-participant-result-v1','result':view})}
    def export_bundle(self,trial_id):
        """Trusted self-contained archive export. Never expose this through participant capability."""
        tid=self._trusted_id(trial_id);trial=self.trials[tid];td=trial.to_dict();stored_results=self.results.get(tid,[])
        if len(stored_results)>MAX_ARCHIVE_RESULTS:raise ListeningError('trusted archive result count exceeds export bound')
        results=[r.to_dict() for r in stored_results]
        stimulus_objects=[self.audio.stimulus(row['stimulus_id']) for row in td['matched_stimuli']];stimuli=[s.to_dict() for s in stimulus_objects]
        for s in stimuli:_validate_stimulus_identity(s)
        by_sid={s['id']:s for s in stimuli}

        raw_groups={}
        for s in stimuli:
            raw=self.audio.raw_pcm(s['id']);key=s['raw_pcm_sha256'];meta=(s['sample_rate_hz'],s['channels'],s['frame_count'])
            if key in raw_groups:
                old=raw_groups[key]
                if old['meta']!=meta or old['pcm']!=raw:raise ListeningError('raw PCM hash reused with conflicting archive metadata')
                old['stimulus_ids'].append(s['id'])
            else:raw_groups[key]={'meta':meta,'pcm':raw,'stimulus_ids':[s['id']]}

        playback_groups={}
        for row in td['matched_stimuli']:
            sid=row['stimulus_id'];s=by_sid[sid];psha=row['playback_sha256'];pcm,sr,ch=self.audio.playback_record(psha);meta=(sr,ch,s['frame_count'])
            if (sr,ch)!=(s['sample_rate_hz'],s['channels']) or len(pcm)!=s['frame_count']*ch*4:raise ListeningError('matched playback shape disagrees with frozen stimulus')
            if psha in playback_groups:
                old=playback_groups[psha]
                if old['meta']!=meta or old['pcm']!=pcm:raise ListeningError('playback hash reused with conflicting archive metadata')
                old['stimulus_ids'].append(sid)
            else:playback_groups[psha]={'meta':meta,'pcm':pcm,'stimulus_ids':[sid]}

        blobs=[]
        for psha,g in sorted(raw_groups.items()):
            sr,ch,frames=g['meta'];blobs.append(_archive_blob('raw-excerpt',psha,g['stimulus_ids'],g['pcm'],sr,ch,frames))
        for psha,g in sorted(playback_groups.items()):
            sr,ch,frames=g['meta'];blobs.append(_archive_blob('matched-playback',psha,g['stimulus_ids'],g['pcm'],sr,ch,frames))
        blobs.sort(key=lambda row:(row['kind'],row['sha256']))
        pcm_bytes=sum(row['byte_length'] for row in blobs)
        if not 1<=len(blobs)<=MAX_ARCHIVE_BLOBS:raise ListeningError('trusted archive blob count exceeds export bound')
        if pcm_bytes>MAX_ARCHIVE_PCM_BYTES:raise ListeningError('trusted archive PCM exceeds export bound')
        bundle={'format':'zaaggenz-listening-bundle','version':TRUSTED_BUNDLE_VERSION,'role':'trusted','stimuli':stimuli,'manifest':td,'results':results,
                'audio':{'encoding':ARCHIVE_ENCODING,'blob_count':len(blobs),'pcm_bytes':pcm_bytes,'blobs':blobs}}
        if _metadata_size(bundle)>MAX_ARCHIVE_METADATA_BYTES:raise ListeningError('trusted archive metadata exceeds export bound')
        bundle['bundle_sha256']=_bundle_sha256(bundle)
        return bundle
    def export_participant_bundle(self,participant_id):
        """Participant-safe export: no seed, trusted trial ID, ABX truth or correctness oracle."""
        tid=self._trusted_id(participant_id,participant_only=True);trial=self.trials[tid];td=trial.to_dict();stimuli=[self.audio.stimulus(row['stimulus_id']).to_dict() for row in td['matched_stimuli']]
        return {'format':'zaaggenz-listening-participant-bundle','version':'1.0.0','role':'participant','stimuli':stimuli,
                'trial':public_trial(trial,participant_id),'results':[public_result(r,participant_id) for r in self.results.get(tid,[])]}
    def _preflight_archive_registration(self,trial,results):
        tid=trial.to_dict()['id'];incoming=[r.to_dict() for r in results]
        if tid in self.trials:
            if self.trials[tid].to_dict()!=trial.to_dict() or [r.to_dict() for r in self.results.get(tid,[])]!=incoming:raise ListeningError('trusted archive conflicts with existing trial state')
            pid=self._trusted_to_participant.get(tid)
            if pid is not None:return tid,pid
        for _ in range(8):
            pid=secrets.token_hex(32);self._validated_participant_id(pid)
            if pid not in self._participant_to_trusted or self._participant_to_trusted[pid]==tid:return tid,pid
        raise ListeningError('unable to allocate participant trial ID for reopened archive')
    def reopen_bundle(self,bundle):
        if type(bundle)is not dict:raise ListeningError('invalid trusted listening bundle')
        if bundle.get('format')=='zaaggenz-listening-participant-bundle':raise ListeningError('participant bundle cannot be reopened as trusted evidence')
        if bundle.get('format')=='zaaggenz-listening-bundle' and bundle.get('version')=='1.0.0':raise ListeningError('legacy trusted bundle 1.0.0 is metadata-only; re-export as 2.0.0 while the original exact audio store is available')
        exact(bundle,{'format','version','role','stimuli','manifest','results','audio','bundle_sha256'},'trusted listening archive')
        if bundle['format']!='zaaggenz-listening-bundle' or bundle['version']!=TRUSTED_BUNDLE_VERSION or bundle['role']!='trusted':raise ListeningError('invalid trusted listening bundle')
        sha(bundle['bundle_sha256'],'bundle_sha256')
        if type(bundle['stimuli'])is not list or not 2<=len(bundle['stimuli'])<=8:raise ListeningError('trusted archive requires 2..8 stimuli')
        if type(bundle['results'])is not list or len(bundle['results'])>MAX_ARCHIVE_RESULTS:raise ListeningError('trusted archive result count exceeds reopen bound')
        audio=bundle['audio'];exact(audio,{'encoding','blob_count','pcm_bytes','blobs'},'trusted archive audio')
        if audio['encoding']!=ARCHIVE_ENCODING:raise ListeningError('unsupported trusted archive audio encoding')
        if type(audio['blobs'])is not list or type(audio['blob_count'])is not int or audio['blob_count']!=len(audio['blobs']) or not 1<=audio['blob_count']<=MAX_ARCHIVE_BLOBS:raise ListeningError('trusted archive blob count exceeds reopen bound')
        if type(audio['pcm_bytes'])is not int or not 1<=audio['pcm_bytes']<=MAX_ARCHIVE_PCM_BYTES:raise ListeningError('trusted archive PCM exceeds reopen bound')

        declared_total=0;seen_keys=set()
        for blob in audio['blobs']:
            exact(blob,{'kind','sha256','byte_length','sample_rate_hz','channels','frame_count','stimulus_ids','data_base64'},'trusted archive audio blob')
            if blob['kind'] not in ('raw-excerpt','matched-playback'):raise ListeningError('invalid trusted archive audio blob kind')
            sha(blob['sha256'],'archive blob sha256')
            if type(blob['byte_length'])is not int or blob['byte_length']<=0:raise ListeningError('archive blob byte_length must be positive integer')
            if type(blob['sample_rate_hz'])is not int or not 8000<=blob['sample_rate_hz']<=384000:raise ListeningError('archive blob sample_rate_hz out of range')
            if type(blob['channels'])is not int or not 1<=blob['channels']<=8:raise ListeningError('archive blob channels out of range')
            if type(blob['frame_count'])is not int or not 1<=blob['frame_count']<=384000*600:raise ListeningError('archive blob frame_count out of range')
            if blob['byte_length']!=blob['frame_count']*blob['channels']*4:raise ListeningError('archive blob byte length does not match PCM shape')
            ids=blob['stimulus_ids']
            if type(ids)is not list or not ids or ids!=sorted(ids) or len(ids)!=len(set(ids)):raise ListeningError('archive blob stimulus IDs must be a sorted unique list')
            for sid in ids:sha(sid,'archive blob stimulus id')
            if type(blob['data_base64'])is not str or len(blob['data_base64'])!=4*((blob['byte_length']+2)//3):raise ListeningError('archive blob base64 length does not match declared PCM size')
            key=(blob['kind'],blob['sha256'])
            if key in seen_keys:raise ListeningError('duplicate trusted archive audio blob')
            seen_keys.add(key);declared_total+=blob['byte_length']
            if declared_total>MAX_ARCHIVE_PCM_BYTES:raise ListeningError('trusted archive PCM exceeds reopen bound')
        if declared_total!=audio['pcm_bytes']:raise ListeningError('trusted archive PCM byte total mismatch')
        if _metadata_size(bundle)>MAX_ARCHIVE_METADATA_BYTES:raise ListeningError('trusted archive metadata exceeds reopen bound')
        if bundle['bundle_sha256']!=_bundle_sha256(bundle):raise ListeningError('trusted archive digest mismatch')

        trial=TrialManifest(bundle['manifest']);stimuli=[Stimulus(s) for s in bundle['stimuli']];td=trial.to_dict();by_sid={s.to_dict()['id']:s for s in stimuli}
        for s in stimuli:_validate_stimulus_identity(s.to_dict())
        expected_sids={r['stimulus_id'] for r in td['matched_stimuli']}
        if len(by_sid)!=len(stimuli) or set(by_sid)!=expected_sids:raise ListeningError('bundle stimulus provenance does not match trial')
        metadata=self._stimulus_metadata(stimuli);results=[TrialResult(r,trial,stimulus_metadata=metadata) for r in bundle['results']]
        playback_refs={}
        for row in td['matched_stimuli']:playback_refs.setdefault(row['playback_sha256'],[]).append(row['stimulus_id'])

        raw_seen=set();playback_seen=set();raw_by_sid={};playback_by_sha={}
        for blob in audio['blobs']:
            ids=blob['stimulus_ids'];psha=blob['sha256'];meta=(blob['sample_rate_hz'],blob['channels'],blob['frame_count'])
            if blob['kind']=='raw-excerpt':
                for sid in ids:
                    s=by_sid.get(sid)
                    if s is None or sid in raw_seen:raise ListeningError('archive raw audio coverage is duplicate or foreign')
                    sd=s.to_dict()
                    if sd['raw_pcm_sha256']!=psha or meta!=(sd['sample_rate_hz'],sd['channels'],sd['frame_count']):raise ListeningError('archive raw audio provenance/shape mismatch')
                    raw_seen.add(sid)
            else:
                expected=sorted(playback_refs.get(psha,[]))
                if ids!=expected or psha in playback_seen:raise ListeningError('archive matched playback coverage is missing, duplicate or foreign')
                for sid in ids:
                    sd=by_sid[sid].to_dict()
                    if meta!=(sd['sample_rate_hz'],sd['channels'],sd['frame_count']):raise ListeningError('archive matched playback shape mismatch')
                playback_seen.add(psha)
            try:encoded=blob['data_base64'].encode('ascii');pcm=base64.b64decode(encoded,validate=True)
            except (UnicodeEncodeError,binascii.Error,ValueError) as e:raise ListeningError('invalid archive PCM base64') from e
            if len(pcm)!=blob['byte_length'] or hashlib.sha256(pcm).hexdigest()!=psha:raise ListeningError('archive PCM content hash mismatch')
            if base64.b64encode(pcm).decode('ascii')!=blob['data_base64']:raise ListeningError('archive PCM base64 is not canonical')
            if blob['kind']=='raw-excerpt':
                for sid in ids:raw_by_sid[sid]=pcm
            else:playback_by_sha[psha]=(pcm,blob['sample_rate_hz'],blob['channels'])
        if raw_seen!=expected_sids:raise ListeningError('trusted archive is missing raw stimulus PCM')
        if playback_seen!=set(playback_refs):raise ListeningError('trusted archive is missing matched playback PCM')

        tid,pid=self._preflight_archive_registration(trial,results)
        self.audio.restore_archive(stimuli,raw_by_sid,playback_by_sha)
        self.trials[tid]=trial;self.results[tid]=results;self._participant_to_trusted[pid]=tid;self._trusted_to_participant[tid]=pid
        return {'trial':public_trial(trial,pid),'results':[r.to_dict() for r in results],'bundle_sha256':bundle['bundle_sha256']}
    @property
    def templates(self):return deepcopy(INSTRUCTIONS)
