from __future__ import annotations
import json,re,secrets,sys
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs,urlparse
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'app'))
import webapp
from zaaggenz_contracts.model import loads
from zaaggenz_jobs import JobError
from zaaggenz_timeline.model import default_document
from zaaggenz_timeline.server import Handler as TimelineHandler
from zaaggenz_timeline.service import TimelineService
from .model import InspectorError
from .service import InspectorService

STATIC=ROOT/'web'/'inspector'
JOB=re.compile(r'/api/inspector/jobs/([0-9a-f]{32})\Z')
AUDIO=re.compile(r'/api/inspector/audio/([AB])\Z')

class Handler(TimelineHandler):
    def log_message(self,fmt,*args):
        if getattr(self.server,'verbose',False):super().log_message(fmt,*args)
    def _origin_ok(self):
        allowed={f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}
        if self.headers.get('Host','') not in allowed:self._error('loopback Host required',403);return False
        origin=self.headers.get('Origin')
        if origin is not None and origin not in {'http://'+x for x in allowed}:self._error('foreign Origin rejected',403);return False
        return True
    def do_GET(self):
        if not self._origin_ok():return
        parsed=urlparse(self.path);path=parsed.path
        try:
            if path=='/api/inspector/bootstrap':return self._json({'token':self.server.token,'state':self.server.inspector.state()})
            if path=='/api/inspector/state':return self._json(self.server.inspector.state())
            match=JOB.fullmatch(path)
            if match:return self._json(self.server.inspector.status(match[1]))
            match=AUDIO.fullmatch(path)
            if match:
                compensated=parse_qs(parsed.query).get('compensated',['0'])[-1]=='1';wave,revision=self.server.inspector.audio(match[1],compensated=compensated)
                return self._binary(wave,'audio/wav',extra_headers={'X-Inspector-Revision':revision,'Cache-Control':'no-store, max-age=0'})
            resources={'/inspector':('index.html','text/html; charset=utf-8'),'/inspector/':('index.html','text/html; charset=utf-8'),
                       '/inspector/app.mjs':('app.mjs','text/javascript; charset=utf-8'),'/inspector/style.css':('style.css','text/css; charset=utf-8')}
            if path in resources:
                filename,mime=resources[path]
                return self._binary((STATIC/filename).read_bytes(),mime,extra_headers={'X-Content-Type-Options':'nosniff','Cache-Control':'no-store, max-age=0',
                    'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; media-src 'self' blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"})
            if path in ('/','/index.html'):
                page=(webapp.STATIC_ROOT/'index.html').read_text(encoding='utf-8');page=page.replace('<body>','<body><nav><a href="/timeline">Open note / clip timeline</a> · <a href="/inspector">Open Research harmonic-comb inspector</a></nav>',1)
                return self._binary(page.encode(),'text/html; charset=utf-8')
            if path.startswith('/api/inspector/') or path.startswith('/inspector/'):return self._error('unknown inspector route',404)
            return super().do_GET()
        except (ValueError,KeyError,InspectorError,JobError) as exc:return self._error(str(exc),400)
    def do_POST(self):
        if not self._origin_ok():return
        path=urlparse(self.path).path
        if not path.startswith('/api/inspector/'):return super().do_POST()
        if not secrets.compare_digest(self.headers.get('X-Zaaggenz-Token',''),self.server.token):return self._error('inspector session token required',403)
        try:
            if self.headers.get('Content-Type','').split(';')[0]!='application/json':raise ValueError('application/json required')
            data=loads(self._read_body(limit=200_000))
            if path=='/api/inspector/bind':
                if type(data)is not dict or set(data)!={'job_id'} or type(data['job_id'])is not str or not re.fullmatch('[0-9a-f]{32}',data['job_id']):raise ValueError('bind request requires a valid timeline job_id only')
                artifact=self.server.timeline.artifact(data['job_id'])
                state=self.server.inspector.bind_artifact(artifact)
                return self._json({'bound':True,'source_binding':state['source_binding'],'state':state})
            if path=='/api/inspector/analyse':
                if type(data)is not dict or set(data)!={'controls'}:raise ValueError('analyse request requires controls only')
                return self._json(self.server.inspector.submit_analysis(data['controls']),202)
            if path=='/api/inspector/freeze':
                if type(data)is not dict or set(data)!={'snapshot_id'}:raise ValueError('freeze request requires snapshot_id')
                return self._json(self.server.inspector.freeze(data['snapshot_id']))
            if path=='/api/inspector/apply':
                if type(data)is not dict or set(data)!={'snapshot_id'}:raise ValueError('apply request requires snapshot_id')
                return self._json(self.server.inspector.apply(data['snapshot_id']))
            if path=='/api/inspector/undo':
                if data!={}:raise ValueError('undo request must be empty')
                return self._json(self.server.inspector.undo())
            if path=='/api/inspector/cancel':
                if type(data)is not dict or set(data)!={'job_id'} or type(data['job_id'])is not str or not re.fullmatch('[0-9a-f]{32}',data['job_id']):raise ValueError('invalid cancellation request')
                return self._json({'cancelled':self.server.inspector.cancel(data['job_id'])})
            return self._error('unknown inspector route',404)
        except (ValueError,KeyError,TypeError,InspectorError,JobError) as exc:return self._error(str(exc),400)

class InspectorServer(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,port=8766,sample_rate=12000,verbose=False,*,timeline=None,demo_fixture=False):
        super().__init__(('127.0.0.1',port),Handler);self.token=secrets.token_urlsafe(32);self.verbose=verbose
        self.initial_document=default_document(sample_rate);self._owns_timeline=timeline is None;self.timeline=TimelineService() if timeline is None else timeline
        self.inspector=InspectorService(sample_rate,demo_fixture=demo_fixture,scheduler=self.timeline.scheduler)
    def server_close(self):
        if hasattr(self,'inspector'):self.inspector.close()
        if getattr(self,'_owns_timeline',False) and hasattr(self,'timeline'):self.timeline.close()
        super().server_close()
