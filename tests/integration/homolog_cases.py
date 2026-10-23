"""Real HTTP smoke over worker-local loopback and the disposable PostgreSQL socket."""
import http.client
import json
import os
import unittest

import psycopg
from psycopg.conninfo import make_conninfo

from careerbrain.db import migrate
from careerbrain.homolog import LOOPBACK, loopback_smoke_server
from careerbrain.server import create_app

DB = os.environ["NEXT_TEST_DATABASE"]
SOCKET = os.environ["NEXT_TEST_SOCKET"]
assert DB.startswith("cbn_test_") and os.environ.get("NEXT_DISPOSABLE_CI") == "1"
WEB_CLIENT_ID = "synthetic-web.apps.googleusercontent.com"
PRESENTER_CLIENT_ID = "synthetic-android.apps.googleusercontent.com"


def conninfo(role):
    return make_conninfo(dbname=DB, user=role, host=SOCKET)


class HomologHttpSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with psycopg.connect(dbname=DB, user="cb_migrator", host=SOCKET, autocommit=True) as connection:
            migrate(connection, target=10)
        cls.application = create_app(auth_conninfo=conninfo("cb_auth"), api_conninfo=conninfo("cb_api"),
                                     web_client_id=WEB_CLIENT_ID, presenter_client_ids=(PRESENTER_CLIENT_ID,),
                                     ingest_conninfo=conninfo("cb_ingest"),
                                     private_worker_conninfo=conninfo("cb_private_worker"))

    def request(self, host, port, method, path, body=None):
        raw = b"" if body is None else json.dumps(body).encode()
        connection = http.client.HTTPConnection(host, port, timeout=2)
        try:
            connection.request(method, path, body=raw,
                               headers={"Content-Type": "application/json",
                                        "Content-Length": str(len(raw))})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_health_and_auth_error_are_real_http_and_sanitized(self):
        with self.assertRaises(ValueError):
            with loopback_smoke_server(self.application, host="0.0.0.0"):
                pass
        with loopback_smoke_server(self.application) as (host, port):
            self.assertEqual(host, LOOPBACK)
            status, headers, body = self.request(host, port, "GET", "/healthz")
            self.assertEqual((status, headers["Cache-Control"], json.loads(body)),
                             (200, "no-store", {"status": "ok"}))
            submitted = {"id_token": "synthetic-invalid-proof", "challenge_id": "synthetic-invalid-challenge"}
            status, headers, body = self.request(host, port, "POST", "/v1/auth/google", submitted)
        self.assertEqual((status, headers["Cache-Control"]), (401, "no-store"))
        error = json.loads(body)
        self.assertEqual(set(error), {"schema_version", "correlation_id", "code", "retryable", "items"})
        self.assertEqual(error["schema_version"], "careerbrain.error.v1")
        self.assertEqual(error["code"], "UNAUTHENTICATED")
        self.assertFalse(error["retryable"])
        self.assertEqual(error["items"], [])
        self.assertNotIn(submitted["id_token"], body.decode())
        self.assertNotIn(submitted["challenge_id"], body.decode())


if __name__ == "__main__":
    unittest.main(verbosity=2)
