"""Loopback-only timeline alongside the unchanged recovered instrument UI."""
from __future__ import annotations
import json
from pathlib import Path
import re
import secrets
import sys
from http.server import ThreadingHTTPServer
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
import webapp
from zaaggenz_contracts.model import loads
from zaaggenz_jobs import JobError
from .model import default_document, exact
from .service import TimelineService

STATIC = ROOT / 'web' / 'timeline'
JOB = re.compile(r'/api/timeline/jobs/([0-9a-f]{32})(/audio)?\Z')


class Handler(webapp.Handler):
    def log_message(self, fmt, *args):
        if getattr(self.server, 'verbose', False):
            super().log_message(fmt, *args)

    def _origin_ok(self):
        allowed = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
        if self.headers.get('Host', '') not in allowed:
            self._error('loopback Host required', 403)
            return False
        origin = self.headers.get('Origin')
        if origin is not None and origin not in {'http://' + host for host in allowed}:
            self._error('foreign Origin rejected', 403)
            return False
        return True

    def do_GET(self):
        if not self._origin_ok():
            return
        path = urlparse(self.path).path
        try:
            if path == '/api/timeline/bootstrap':
                session = getattr(self.server, 'session', None)
                document = self.server.initial_document if session is None else session.document()
                payload = {'document': document.to_dict(), 'token': self.server.token}
                if session is not None:
                    payload['session'] = session.snapshot()
                return self._json(payload)
            match = JOB.fullmatch(path)
            if match:
                if match[2]:
                    wave, revision = self.server.timeline.wave(match[1])
                    return self._binary(wave, 'audio/wav', extra_headers={'X-Timeline-Revision': revision,
                        'Content-Disposition': 'attachment; filename="zaaggenz-timeline.wav"'})
                return self._json(self.server.timeline.status(match[1]))
            resources = {'/timeline': ('index.html', 'text/html; charset=utf-8'),
                         '/timeline/': ('index.html', 'text/html; charset=utf-8'),
                         '/timeline/app.mjs': ('app.mjs', 'text/javascript; charset=utf-8'),
                         '/timeline/editor.mjs': ('editor.mjs', 'text/javascript; charset=utf-8'),
                         '/timeline/style.css': ('style.css', 'text/css; charset=utf-8')}
            if path in resources:
                filename, mime = resources[path]
                return self._binary((STATIC / filename).read_bytes(), mime,
                                    extra_headers={'X-Content-Type-Options': 'nosniff',
                                     'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; media-src 'self' blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"})
            if path == '/timeline/jobs_transport.mjs':
                return self._binary((ROOT / 'web' / 'jobs_transport.mjs').read_bytes(), 'text/javascript')
            if path in ('/', '/index.html'):
                page = (webapp.STATIC_ROOT / 'index.html').read_text(encoding='utf-8')
                page = page.replace('<body>', '<body><nav><a href="/timeline">Open note / clip timeline</a></nav>', 1)
                return self._binary(page.encode(), 'text/html; charset=utf-8')
            if path.startswith('/api/timeline/') or path.startswith('/timeline/'):
                return self._error('unknown timeline route', 404)
            return super().do_GET()
        except (ValueError, JobError, KeyError) as exc:
            return self._error(str(exc), 400)

    def do_POST(self):
        if not self._origin_ok():
            return
        path = urlparse(self.path).path
        if not path.startswith('/api/timeline/'):
            return super().do_POST()
        if not secrets.compare_digest(self.headers.get('X-Zaaggenz-Token', ''), self.server.token):
            return self._error('timeline session token required', 403)
        try:
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                raise ValueError('application/json required')
            data = loads(self._read_body(limit=2_000_000))
            if path == '/api/timeline/validate':
                exact(data, {'document'}, 'validation request')
                result = self.server.timeline.validate(data['document'])
                session = getattr(self.server, 'session', None)
                if session is not None:
                    result['session'] = session.accept_document(data['document'])
                return self._json(result)
            if path == '/api/timeline/render':
                exact(data, {'document', 'region', 'name'}, 'render request')
                result = self.server.timeline.submit(data['document'], data['region'], data['name'])
                session = getattr(self.server, 'session', None)
                if session is not None:
                    result['session'] = session.accept_document(data['document'])
                return self._json(result, 202)
            if path == '/api/timeline/cancel':
                exact(data, {'job_id'}, 'cancellation request')
                if type(data['job_id']) is not str or not re.fullmatch('[0-9a-f]{32}', data['job_id']):
                    raise ValueError('invalid job ID')
                return self._json({'cancelled': self.server.timeline.cancel(data['job_id'])})
            return self._error('unknown timeline route', 404)
        except (ValueError, JobError, KeyError, TypeError) as exc:
            return self._error(str(exc), 400)


class TimelineServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, port=8765, sample_rate=48000, verbose=False):
        super().__init__(('127.0.0.1', port), Handler)
        self.token = secrets.token_urlsafe(32)
        self.verbose = verbose
        self.initial_document = default_document(sample_rate)
        self.timeline = TimelineService()

    def server_close(self):
        if hasattr(self, 'timeline'):
            self.timeline.close()
        super().server_close()
