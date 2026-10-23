"""Production WSGI construction; configuration is supplied only at runtime."""
from __future__ import annotations

import json
import logging
import os
from typing import Callable

from .server import create_app

LOG = logging.getLogger('careerbrain.runtime')


def _required(name: str) -> str:
    value = os.environ.get(name, '')
    if not value:
        raise RuntimeError(f'missing runtime setting: {name}')
    return value


def build_application():
    app = create_app(
        auth_conninfo=_required('CBN_AUTH_CONNINFO'),
        api_conninfo=_required('CBN_API_CONNINFO'),
        ingest_conninfo=_required('CBN_INGEST_CONNINFO'),
        private_worker_conninfo=_required('CBN_PRIVATE_WORKER_CONNINFO'),
        web_client_id=_required('CBN_WEB_CLIENT_ID'),
        presenter_client_ids=tuple(filter(None, _required('CBN_PRESENTER_CLIENT_IDS').split(','))),
    )
    return app


class RuntimeApplication:
    def __init__(self):
        self.application = build_application()

    def _ready(self) -> bool:
        try:
            for pool in (self.application.identity.service.auth_pool,
                         self.application.identity.service.api_pool,
                         self.application.ingestion.pool,
                         self.application.resume.service.worker_pool,
                         self.application.mobile.pool):
                with pool.connection() as connection:
                    connection.execute('SELECT 1').fetchone()
            return True
        except Exception:
            LOG.warning(json.dumps({'component': 'careerbrain-api', 'event': 'readiness_failed'}))
            return False

    def __call__(self, environ, start_response):
        method, path = environ.get('REQUEST_METHOD'), environ.get('PATH_INFO')
        if method == 'GET' and path == '/healthz':
            return self._response(start_response, '200 OK', {'status': 'alive'})
        if method == 'GET' and path == '/readyz':
            ready = self._ready()
            return self._response(start_response, '200 OK' if ready else '503 Service Unavailable',
                                  {'status': 'ready' if ready else 'unavailable'})
        return self.application(environ, start_response)

    @staticmethod
    def _response(start_response: Callable, status: str, value: dict):
        body = json.dumps(value, separators=(',', ':')).encode()
        start_response(status, [('Content-Type', 'application/json'), ('Content-Length', str(len(body))),
                                ('Cache-Control', 'no-store')])
        return [body]


application = RuntimeApplication()
