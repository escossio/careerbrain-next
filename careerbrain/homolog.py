"""Disposable loopback WSGI smoke harness; never a production HTTP server."""
from __future__ import annotations

from contextlib import contextmanager
import json
import threading
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server


LOOPBACK = "127.0.0.1"


class QuietRequestHandler(WSGIRequestHandler):
    """Do not emit request paths, headers, bodies, or credentials during smoke."""

    def log_message(self, format, *args):
        return


class LoopbackOnlyServer(WSGIServer):
    """Reject every bind address except the IPv4 loopback used by the smoke test."""

    def server_bind(self):
        if self.server_address[0] != LOOPBACK:
            raise ValueError("Homolog smoke accepts loopback only")
        return super().server_bind()


class HomologWSGI:
    """Expose only a minimal health check in front of the configured application."""

    def __init__(self, application):
        self.application = application

    def __call__(self, environ, start_response):
        if environ.get("REQUEST_METHOD") == "GET" and environ.get("PATH_INFO") == "/healthz":
            body = json.dumps({"status": "ok"}, separators=(",", ":")).encode()
            start_response("200 OK", [("Content-Type", "application/json"),
                                      ("Content-Length", str(len(body))),
                                      ("Cache-Control", "no-store")])
            return [body]
        return self.application(environ, start_response)

    def close(self):
        self.application.close()


@contextmanager
def loopback_smoke_server(application, *, host=LOOPBACK):
    """Serve one disposable application only on loopback and always close its pools."""
    if host != LOOPBACK:
        raise ValueError("Homolog smoke accepts loopback only")
    wrapped = HomologWSGI(application)
    server = make_server(host, 0, wrapped, server_class=LoopbackOnlyServer,
                         handler_class=QuietRequestHandler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        yield server.server_address
    finally:
        try:
            server.shutdown()
        finally:
            thread.join(timeout=2)
            try:
                server.server_close()
            finally:
                wrapped.close()
