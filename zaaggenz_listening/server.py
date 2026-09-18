"""Loopback-only listening workflow layered beside the normal Compose timeline."""
from __future__ import annotations
from pathlib import Path
import re,secrets
from http.server import ThreadingHTTPServer
from urllib.parse import urlparse
from zaaggenz_contracts.model import loads
from zaaggenz_timeline.model import default_document
from zaaggenz_timeline.service import TimelineService
from zaaggenz_timeline.server import Handler as TimelineHandler
from zaaggenz_web_release import build_web_releases
from .archive import (ARCHIVE_MIME, ListeningArchiveLimits, export_service_archive,
                      reopen_service_archive)
from .model import ListeningError,ENDPOINTS,exact
from .service import ListeningService

ROOT=Path(__file__).resolve().parents[1];STATIC=ROOT/'web'/'listening'
AUDIO=re.compile(r'/api/listening/audio/([0-9a-f]{64})\.wav\Z')
ABX=re.compile(r'/api/listening/trial/([0-9a-f]{64})/X\.wav\Z')
TRUSTED_PATHS=frozenset(('/api/listening/trusted-export','/api/listening/reopen',
                         '/api/listening/trusted-archive','/api/listening/reopen-archive'))
ARCHIVE_LIMITS=ListeningArchiveLimits()

class Handler(TimelineHandler):
    def _participant_ok(self):
        return secrets.compare_digest(self.headers.get('X-Zaaggenz-Token',''),self.server.token)
    def _trusted_ok(self):
        return secrets.compare_digest(self.headers.get('X-Zaaggenz-Trusted-Token',''),self.server.trusted_token)
    def do_GET(self):
        if not self._origin_ok():return
        path=urlparse(self.path).path
        try:
            if path=='/api/listening/bootstrap':
                return self._json({'token':self.server.token,
                    'web_release':self._release_payload('listening'),
                    'capability':{'format':'zaaggenz-listening-capability','version':'1.0.0','role':'participant',
                                  'permissions':['freeze','match','create-trial','play','submit','participant-export','participant-archive']},
                    'templates':self.server.listening.templates,'endpoints':list(ENDPOINTS),'compose_independent':True})
            m=AUDIO.fullmatch(path)
            if m:return self._binary(self.server.listening.audio.wav(m[1]),'audio/wav',extra_headers={'X-Playback-SHA256':m[1],'Cache-Control':'no-store'})
            x=ABX.fullmatch(path)
            if x:
                trial=self.server.listening.participant_manifest(x[1]);td=trial.to_dict()
                if td['design']!='abx':raise ListeningError('X playback belongs only to ABX trials')
                sid=td['presentation_order'][0 if td['abx_truth']=='A' else 1]
                row=next(r for r in td['matched_stimuli'] if r['stimulus_id']==sid)
                return self._binary(self.server.listening.audio.wav(row['playback_sha256']),'audio/wav',extra_headers={'Cache-Control':'no-store'})
            resources={'/listen':('index.html','text/html; charset=utf-8'),'/listen/':('index.html','text/html; charset=utf-8'),'/listen/app.mjs':('app.mjs','text/javascript; charset=utf-8'),'/listen/style.css':('style.css','text/css; charset=utf-8')}
            if path in resources:
                filename,mime=resources[path]
                return self._workspace_asset('listening',filename,mime,STATIC/filename,'/listen')
            return super().do_GET()
        except (ListeningError,ValueError,KeyError) as e:return self._error(str(e),400)
    def do_POST(self):
        if not self._origin_ok():return
        path=urlparse(self.path).path
        if not path.startswith('/api/listening/'):return super().do_POST()
        if not self._frontend_release_ok('listening'):return
        if path in TRUSTED_PATHS:
            if not self._trusted_ok():return self._error('trusted listening capability required',403)
        elif not self._participant_ok():return self._error('participant listening capability required',403)
        try:
            content_type=self.headers.get('Content-Type','').split(';')[0]
            if path=='/api/listening/reopen-archive':
                if content_type!=ARCHIVE_MIME:raise ListeningError(f'{ARCHIVE_MIME} required')
                payload=self._read_body(limit=ARCHIVE_LIMITS.max_archive_bytes)
                return self._json(reopen_service_archive(self.server.listening,payload,limits=ARCHIVE_LIMITS))
            if content_type!='application/json':raise ListeningError('application/json required')
            d=loads(self._read_body(limit=2_000_000))
            if path=='/api/listening/freeze':
                exact(d,{'job_id','name','start_frame','end_frame'},'freeze request');return self._json(self.server.listening.freeze_job(d['job_id'],d['name'],d['start_frame'],d['end_frame']))
            if path=='/api/listening/match':
                exact(d,{'stimulus_ids','target_rms_dbfs','peak_ceiling_dbfs'},'match request');return self._json({'matched_stimuli':self.server.listening.match(d['stimulus_ids'],d['target_rms_dbfs'],d['peak_ceiling_dbfs'])})
            if path=='/api/listening/trial':
                exact(d,{'title','design','matched_stimuli','seed','endpoints','instruction_template'},'trial request');return self._json({'trial':self.server.listening.create_participant_trial(d['title'],d['design'],d['matched_stimuli'],d['seed'],d['endpoints'],d['instruction_template'])},201)
            if path=='/api/listening/submit':
                exact(d,{'trial_id','result'},'submit request');return self._json(self.server.listening.submit_participant(d['trial_id'],d['result']),201)
            if path=='/api/listening/export':
                exact(d,{'trial_id'},'export request');return self._json(self.server.listening.export_participant_bundle(d['trial_id']))
            if path=='/api/listening/trusted-export':
                exact(d,{'trial_id'},'trusted export request');return self._json(self.server.listening.export_bundle(d['trial_id']))
            if path=='/api/listening/archive':
                exact(d,{'trial_id'},'participant archive request')
                payload=export_service_archive(self.server.listening,d['trial_id'],role='participant',limits=ARCHIVE_LIMITS)
                return self._binary(payload,ARCHIVE_MIME,extra_headers={'Cache-Control':'no-store','Content-Disposition':'attachment; filename="zaaggenz-listening.zgla"'})
            if path=='/api/listening/trusted-archive':
                exact(d,{'trial_id'},'trusted archive request')
                payload=export_service_archive(self.server.listening,d['trial_id'],role='trusted',limits=ARCHIVE_LIMITS)
                return self._binary(payload,ARCHIVE_MIME,extra_headers={'Cache-Control':'no-store','Content-Disposition':'attachment; filename="zaaggenz-listening-trusted.zgla"'})
            if path=='/api/listening/reopen':
                exact(d,{'bundle'},'reopen request');return self._json(self.server.listening.reopen_bundle(d['bundle']))
            return self._error('unknown listening route',404)
        except (ListeningError,ValueError,KeyError,TypeError) as e:return self._error(str(e),400)

class ListeningServer(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,port=8765,sample_rate=48000,verbose=False,*,timeline=None):
        super().__init__(('127.0.0.1',port),Handler);self.token=secrets.token_urlsafe(32);self.trusted_token=secrets.token_urlsafe(32);self.verbose=verbose;self.web_releases=build_web_releases(ROOT);self.initial_document=default_document(sample_rate)
        self._owns_timeline=timeline is None;self.timeline=TimelineService() if timeline is None else timeline;self.listening=ListeningService(self.timeline)
    def server_close(self):
        if getattr(self,'_owns_timeline',False) and hasattr(self,'timeline'):self.timeline.close()
        super().server_close()
