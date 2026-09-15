"""Single-process loopback runtime for Compose and accepted research sidecars."""
from __future__ import annotations
from pathlib import Path
import secrets
import sys
from http.server import ThreadingHTTPServer
from urllib.parse import urlparse

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
import webapp
from zaaggenz_jobs import JobScheduler
from zaaggenz_timeline.model import default_document
from zaaggenz_timeline.service import TimelineService,scheduler_limits
from zaaggenz_timeline.server import Handler as TimelineHandler
from zaaggenz_listening.service import ListeningService
from zaaggenz_listening.server import Handler as ListeningHandler
from zaaggenz_inspector.service import InspectorService
from zaaggenz_inspector.server import Handler as InspectorHandler
from zaaggenz_vocal.service import VocalService
from zaaggenz_vocal.server import Handler as VocalHandler
from .session import RuntimeSession


class Handler(ListeningHandler,InspectorHandler,VocalHandler):
    """Compose all accepted route modules on one origin.

    Unknown routes deliberately flow through the cooperative Handler MRO and
    finish in TimelineHandler/webapp.  Each existing module therefore retains
    its Host/Origin, request-bound and CSP behaviour.
    """
    def do_GET(self):
        if not self._origin_ok():return
        path=urlparse(self.path).path
        if path=='/api/runtime/bootstrap':
            return self._json({'format':'zaaggenz-runtime-bootstrap','version':'1.0.0',
                'token':self.server.token,'session':self.server.session.snapshot(),
                'routes':{'compose':'/timeline','listening':'/listen','inspector':'/inspector','vocal':'/vocal','legacy':'/'},
                'capabilities':{'session':'compose-participant','listening_participant':True,'listening_trusted':'separate-server-held-capability'},
                'resource_owner':{'scheduler':'runtime','timeline':'runtime-session','shutdown':'runtime'}})
        if path in ('/','/index.html'):
            page=(webapp.STATIC_ROOT/'index.html').read_text(encoding='utf-8')
            nav='<nav id="zaaggenz-workspaces"><a href="/timeline">Compose timeline</a> · <a href="/listen">Listening</a> · <a href="/inspector">Inspector</a> · <a href="/vocal">Vocal gestures</a></nav>'
            page=page.replace('<body>','<body>'+nav,1)
            return self._binary(page.encode(),'text/html; charset=utf-8',extra_headers={'X-Content-Type-Options':'nosniff',
                'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; media-src 'self' blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"})
        return super().do_GET()


class ZaaggenzServer(ThreadingHTTPServer):
    """One authoritative local application/session and one bounded scheduler."""
    daemon_threads=True
    def __init__(self,port=8765,sample_rate=48000,verbose=False,*,demo_fixture=False):
        super().__init__(('127.0.0.1',port),Handler)
        self.verbose=verbose;self.token=secrets.token_urlsafe(32);self.trusted_token=secrets.token_urlsafe(32);self._closed=False
        self.scheduler=None
        try:
            initial=default_document(sample_rate);self.initial_document=initial;self.session=RuntimeSession(initial)
            self.scheduler=JobScheduler(scheduler_limits())
            self.timeline=TimelineService(self.scheduler)
            self.listening=ListeningService(self.timeline)
            self.inspector=InspectorService(sample_rate,demo_fixture=demo_fixture,scheduler=self.scheduler,current_revision_provider=self.session.current_revision_id)
            self.vocal=VocalService()
        except Exception:
            if self.scheduler is not None:
                self.scheduler.shutdown(cancel=True,timeout=5)
            super().server_close();raise

    def server_close(self):
        if self._closed:return
        self._closed=True
        try:
            if hasattr(self,'inspector'):self.inspector.close()
            if hasattr(self,'timeline'):self.timeline.close()
            if self.scheduler is not None:self.scheduler.shutdown(cancel=True,timeout=5)
        finally:
            super().server_close()
