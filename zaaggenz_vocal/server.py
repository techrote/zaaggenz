"""Loopback-only optional vocal capture UI layered beside the accepted Compose timeline."""
from __future__ import annotations
from pathlib import Path
import re,secrets
from http.server import ThreadingHTTPServer
from urllib.parse import urlparse
from zaaggenz_contracts.model import loads
from zaaggenz_timeline.model import default_document
from zaaggenz_timeline.service import TimelineService
from zaaggenz_timeline.server import Handler as TimelineHandler
from .model import VocalCaptureError,exact
from .service import VocalService

ROOT=Path(__file__).resolve().parents[1];STATIC=ROOT/'web'/'vocal';SOURCE=re.compile(r'/api/vocal/source/(capture-[0-9a-f]{16})/audio\Z')

class Handler(TimelineHandler):
    def _with_source_session(self,payload):
        session=getattr(self.server,'session',None)
        if session is None:return payload
        return {**payload,'source_session':session.snapshot(),'application_policy':'proposal-only; explicit Compose import/apply required'}
    def do_GET(self):
        if not self._origin_ok():return
        path=urlparse(self.path).path
        try:
            if path=='/api/vocal/bootstrap':
                payload={'token':self.server.token,'registry':self.server.vocal.registry.to_dict(),'capture_state':'idle; microphone permission has not been requested','microphone_optional':True}
                return self._json(self._with_source_session(payload))
            match=SOURCE.fullmatch(path)
            if match:
                wave,sr=self.server.vocal.wave(match[1]);return self._binary(wave,'audio/wav',extra_headers={'X-Capture-Sample-Rate':sr})
            resources={'/vocal':('index.html','text/html; charset=utf-8'),'/vocal/':('index.html','text/html; charset=utf-8'),
                       '/vocal/app.mjs':('app.mjs','text/javascript; charset=utf-8'),'/vocal/editor.mjs':('editor.mjs','text/javascript; charset=utf-8'),'/vocal/style.css':('style.css','text/css; charset=utf-8')}
            if path in resources:
                filename,mime=resources[path]
                return self._binary((STATIC/filename).read_bytes(),mime,extra_headers={'X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; media-src 'self' blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"})
            return super().do_GET()
        except (VocalCaptureError,ValueError,KeyError) as exc:return self._error(str(exc),400)
    def do_POST(self):
        if not self._origin_ok():return
        path=urlparse(self.path).path
        if not path.startswith('/api/vocal/'):return super().do_POST()
        if not secrets.compare_digest(self.headers.get('X-Zaaggenz-Token',''),self.server.token):return self._error('vocal session token required',403)
        try:
            if path=='/api/vocal/upload':
                if self.headers.get('Content-Type','').split(';')[0] not in ('audio/wav','audio/wave','audio/x-wav'):raise VocalCaptureError('WAV content type required')
                origin=self.headers.get('X-Capture-Origin','local-import')
                if origin not in ('local-import','local-recording'):raise VocalCaptureError('capture origin must be local-import or local-recording')
                return self._json(self._with_source_session(self.server.vocal.ingest_wav(self._read_body(limit=20_000_000),origin)),201)
            if self.headers.get('Content-Type','').split(';')[0]!='application/json':raise VocalCaptureError('application/json required')
            data=loads(self._read_body(limit=2_000_000))
            if path=='/api/vocal/analyse':
                exact(data,{'source_id','dictionary_id','grid_beats'},'analyse request')
                return self._json(self._with_source_session(self.server.vocal.analyse(data['source_id'],data['dictionary_id'],data['grid_beats'])))
            if path=='/api/vocal/compile':
                exact(data,{'edit'},'compile request');return self._json(self._with_source_session(self.server.vocal.compile(data['edit'])))
            if path=='/api/vocal/discard':
                exact(data,{'source_id','edit'},'discard request');return self._json(self._with_source_session(self.server.vocal.discard(data['source_id'],data['edit'])))
            return self._error('unknown vocal route',404)
        except (VocalCaptureError,ValueError,KeyError,TypeError) as exc:return self._error(str(exc),400)

class VocalServer(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,port=8765,sample_rate=48000,verbose=False,*,timeline=None):
        super().__init__(('127.0.0.1',port),Handler);self.token=secrets.token_urlsafe(32);self.verbose=verbose;self.initial_document=default_document(sample_rate)
        self._owns_timeline=timeline is None;self.timeline=TimelineService() if timeline is None else timeline;self.vocal=VocalService()
    def server_close(self):
        if getattr(self,'_owns_timeline',False) and hasattr(self,'timeline'):self.timeline.close()
        super().server_close()
