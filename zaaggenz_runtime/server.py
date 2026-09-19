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
from zaaggenz_listening.service import ListeningService
from zaaggenz_listening.server import Handler as ListeningHandler
from zaaggenz_inspector.service import InspectorService
from zaaggenz_inspector.server import Handler as InspectorHandler
from zaaggenz_vocal.service import VocalService
from zaaggenz_vocal.server import Handler as VocalHandler
from zaaggenz_web_release import WEB_API_VERSION,build_web_releases,cache_headers
from .session import RuntimeSession

RESEARCH_CSP="default-src 'self'; script-src 'none'; style-src 'self'; media-src 'self' blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"


class Handler(ListeningHandler,InspectorHandler,VocalHandler):
    """Compose all accepted route modules on one origin.

    Unknown routes deliberately flow through the cooperative Handler MRO and
    finish in the Timeline/webapp handler. Each existing module therefore
    retains its Host/Origin, request-bound and CSP behaviour.
    """
    def _research_page(self):
        """Serve a read-only Research workspace hub bound to this runtime session.

        The hub deliberately has no script and no mutation controls.  It exposes
        provenance and routes into accepted research tools while keeping every
        transform/apply action inside the tool that owns that explicit contract.
        """
        session=self.server.session.snapshot();release=self.server.web_releases['timeline']
        rid=session['timeline_revision_id'];project=session['project_revision_id'];project_sha=session['project_sha256']
        page=f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>zaaggenz · Research workspace</title><link rel="stylesheet" href="/timeline/style.css?zg-release={release.release_id}"></head><body id="research-workspace"><header><div><span class="eyebrow">ZAAGGENZ / RESEARCH</span><h1>Inspect, compare & record</h1><p>Derived evidence stays separate from the working Compose project. Research never applies a transform implicitly.</p></div><a class="legacy" id="compose-workspace-link" href="/timeline">Return to Compose ↗</a></header><main><section class="deck" aria-labelledby="research-boundary"><h2 id="research-boundary">Current source boundary</h2><p>All tools below derive from immutable source revisions or explicit captures. A result from an older Compose revision remains evidence, but must be treated as stale for publication/apply against the current project.</p><dl><dt>Timeline revision</dt><dd><code id="research-timeline-revision">{rid}</code></dd><dt>Project revision</dt><dd><code>{project}</code></dd><dt>Project SHA-256</dt><dd><code>{project_sha}</code></dd><dt>Workspace release</dt><dd><code>{release.release_id}</code></dd></dl></section><section class="workspace" aria-label="Research tools"><div class="deck"><h2>Inspector · before / after</h2><p>Bind an exact completed Compose artifact, inspect measured pitch/tuning and spectral state, and compare a proposal without overwriting Compose.</p><a class="button" id="research-inspector" href="/inspector">Open Inspector</a></div><div class="deck"><h2>Listening · matched comparisons</h2><p>Freeze exact stimuli, level-match comparisons, create blinded trial manifests, record observations and export participant-safe evidence.</p><a class="button" id="research-listening" href="/listen">Open Listening</a></div><div class="deck"><h2>Vocal · derived gesture proposals</h2><p>Capture or import a local gesture and compile a proposal. The proposal-only contract requires explicit Compose import/apply.</p><a class="button" id="research-vocal" href="/vocal">Open Vocal</a></div></section><details class="deck" open><summary>Workspace contract and disclosure</summary><p><strong>Compose is the default.</strong> Making, rendering, saving and exporting music does not require a study or trial. Research records are immutable derived state and cannot silently replace the working project.</p><p>Inspector, Listening and Vocal retain their own method/version, measured-state and provenance disclosures. The browser/API release identity for this hub is the Timeline workspace release above; the accepted sidecar release identities remain available from <code>/api/runtime/bootstrap</code>.</p><p><a href="/">Recovered full instrument</a> · <a href="/timeline">Compose timeline</a></p></details></main></body></html>'''
        headers=cache_headers(release);headers['Content-Security-Policy']=RESEARCH_CSP
        return self._binary(page.encode(),'text/html; charset=utf-8',extra_headers=headers)

    def do_GET(self):
        if not self._origin_ok():return
        path=urlparse(self.path).path
        if path=='/api/runtime/bootstrap':
            return self._json({'format':'zaaggenz-runtime-bootstrap','version':'1.0.0',
                'api_version':WEB_API_VERSION,
                'web_releases':{name:release.to_dict() for name,release in self.server.web_releases.items()},
                'token':self.server.token,'session':self.server.session.snapshot(),
                'routes':{'compose':'/timeline','research':'/research','listening':'/listen','inspector':'/inspector','vocal':'/vocal','legacy':'/'},
                'workspace_policy':{'default':'compose','compose_requires_research':False,
                    'research_state':'derived-and-isolated','research_apply':'explicit-only'},
                'capabilities':{'session':'compose-participant','listening_participant':True,'listening_trusted':'separate-server-held-capability'},
                'resource_owner':{'scheduler':'runtime','timeline':'runtime-session','shutdown':'runtime'}})
        if path=='/research':
            return self._research_page()
        if path in ('/','/index.html'):
            page=(webapp.STATIC_ROOT/'index.html').read_text(encoding='utf-8')
            nav='<nav id="zaaggenz-workspaces"><a href="/timeline">Compose timeline</a> · <a href="/research">Research</a> · <a href="/listen">Listening</a> · <a href="/inspector">Inspector</a> · <a href="/vocal">Vocal gestures</a></nav>'
            page=page.replace('<body>','<body>'+nav,1)
            # Preserve the recovered application's response policy here: adding
            # a stricter CSP to this legacy page could disable its inline UI.
            # Each accepted sidecar keeps its existing restrictive CSP.
            return self._binary(page.encode(),'text/html; charset=utf-8')
        return super().do_GET()


class ZaaggenzServer(ThreadingHTTPServer):
    """One authoritative local application/session and one bounded scheduler."""
    daemon_threads=True
    def __init__(self,port=8765,sample_rate=48000,verbose=False,*,demo_fixture=False):
        super().__init__(('127.0.0.1',port),Handler)
        self.verbose=verbose;self.token=secrets.token_urlsafe(32);self.trusted_token=secrets.token_urlsafe(32);self._closed=False
        self.web_releases=build_web_releases(ROOT,unified_runtime=True)
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
