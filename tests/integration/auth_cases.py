"""Signed synthetic Google proofs and real SQL roles on disposable PostgreSQL."""
import concurrent.futures
import io
import json
import os
import time
import unittest
from uuid import UUID, uuid4

import jwt
import psycopg
from cryptography.hazmat.primitives.asymmetric import rsa
from psycopg.conninfo import make_conninfo

from careerbrain.api import IdentityAPI
from careerbrain.auth import AuthService, Denied, GoogleVerifier, digest
from careerbrain.db import migrate, tenant_pool, tenant_transaction

DB = os.environ['NEXT_TEST_DATABASE']
SOCKET = os.environ['NEXT_TEST_SOCKET']
assert DB.startswith('cbn_test_') and os.environ.get('NEXT_DISPOSABLE_CI') == '1'
AUDIENCE = 'synthetic-web.apps.googleusercontent.com'
PRESENTER = 'synthetic-android.apps.googleusercontent.com'
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def connect(role='postgres'):
    return psycopg.connect(dbname=DB, user=role, host=SOCKET, autocommit=True)


class AuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with connect('cb_migrator') as conn:
            migrate(conn, target=3)
            migrate(conn, target=3)
        cls.auth_pool = tenant_pool(make_conninfo(dbname=DB, user='cb_auth', host=SOCKET),max_size=4)
        cls.api_pool = tenant_pool(make_conninfo(dbname=DB, user='cb_api', host=SOCKET),max_size=4)
        cls.auth_pool.wait(timeout=5)
        cls.api_pool.wait(timeout=5)
        verifier = GoogleVerifier(AUDIENCE, (PRESENTER,), key_provider=lambda _: KEY.public_key())
        cls.service = AuthService(cls.auth_pool, cls.api_pool, verifier)
        cls.api = IdentityAPI(cls.service)

    @classmethod
    def tearDownClass(cls):
        cls.auth_pool.close()
        cls.api_pool.close()

    def proof(self, challenge, subject=None, **changes):
        now = int(time.time())
        claims = {'iss': 'https://accounts.google.com', 'aud': AUDIENCE,
                  'azp': PRESENTER, 'sub': subject or 'synthetic-' + str(uuid4()),
                  'iat': now, 'exp': now + 3600, 'nonce': challenge['nonce']}
        claims.update(changes)
        return jwt.encode(claims, KEY, algorithm='RS256', headers={'kid': 'synthetic-kid'})

    def login(self, subject=None):
        challenge = self.service.challenge()
        return self.service.login(self.proof(challenge,subject), challenge['challenge_id'])

    def request(self, method, path, body=None, access=None):
        raw = b'' if body is None else json.dumps(body).encode()
        env = {'REQUEST_METHOD': method, 'PATH_INFO': path,
               'CONTENT_LENGTH': str(len(raw)), 'CONTENT_TYPE': 'application/json',
               'wsgi.input': io.BytesIO(raw)}
        if access is not None:
            env['HTTP_AUTHORIZATION'] = 'Bearer ' + access
        meta = []
        result = b''.join(self.api(env, lambda status, headers: meta.append((status, headers))))
        return meta[0][0], json.loads(result) if result else None

    def test_proof_is_signed_and_claims_are_fail_closed(self):
        challenge = self.service.challenge()
        valid = self.proof(challenge)
        self.assertTrue(self.service.verifier.verify(valid, challenge['nonce']))
        now = int(time.time())
        bad = [
            self.proof(challenge, aud='wrong.apps.googleusercontent.com'),
            self.proof(challenge, iss='https://example.org'),
            self.proof(challenge, exp=now-120),
            self.proof(challenge, iat=now+120),
            self.proof(challenge, nonce='other-nonce-with-enough-characters-0001'),
            self.proof(challenge, azp='wrong.apps.googleusercontent.com'),
            self.proof(challenge, sub=''),
            jwt.encode({'iss':'https://accounts.google.com','aud':AUDIENCE,'sub':'synthetic',
                        'iat':now,'exp':now+60,'nonce':challenge['nonce']},
                       'synthetic-key',algorithm='HS256',headers={'kid':'synthetic-kid'}),
        ]
        for token in bad:
            with self.subTest(token_type=jwt.get_unverified_header(token)['alg']),self.assertRaises(Denied):
                self.service.login(token,challenge['challenge_id'])
        self.assertEqual(self.service.login(valid,challenge['challenge_id'])['expires_in'],900)

    def test_challenge_replay_and_expiry(self):
        challenge = self.service.challenge()
        proof = self.proof(challenge)
        self.service.login(proof,challenge['challenge_id'])
        with self.assertRaises(Denied):self.service.login(proof,challenge['challenge_id'])
        expired = self.service.challenge()
        with connect() as c:c.execute("UPDATE auth.challenges SET expires_at=transaction_timestamp()-interval '1 second' WHERE id=%s",(expired['challenge_id'],))
        with self.assertRaises(Denied):self.service.login(self.proof(expired),expired['challenge_id'])

    def test_identity_stable_and_cross_user_isolated(self):
        subject = 'synthetic-stable-' + str(uuid4())
        first, second = self.login(subject), self.login(subject)
        other = self.login()
        a = self.service.identity(first['access_token'])
        b = self.service.identity(second['access_token'])
        c = self.service.identity(other['access_token'])
        self.assertEqual((a['user_id'],a['tenant_id'],a['account_created_at']),
                         (b['user_id'],b['tenant_id'],b['account_created_at']))
        self.assertNotEqual(a['tenant_id'],c['tenant_id'])
        self.assertEqual(a['issuer'],'https://accounts.google.com')
        with tenant_transaction(self.api_pool, a['tenant_id']) as conn:
            self.assertEqual(conn.execute('SELECT id FROM private.tenants').fetchall(),
                             [(UUID(a['tenant_id']),)])

    def test_refresh_rotation_replay_revokes_family_and_logout(self):
        original = self.login()
        rotated = self.service.refresh(original['refresh_token'])
        with self.assertRaises(Denied):self.service.identity(original['access_token'])
        self.service.identity(rotated['access_token'])
        with self.assertRaises(Denied):self.service.refresh(original['refresh_token'])
        with self.assertRaises(Denied):self.service.identity(rotated['access_token'])
        with self.assertRaises(Denied):self.service.refresh(rotated['refresh_token'])
        another = self.login()
        self.service.logout(another['access_token'])
        with self.assertRaises(Denied):self.service.identity(another['access_token'])

    def test_concurrent_rotation_never_issues_two_usable_tokens(self):
        original = self.login()
        def rotate(_):
            try:return self.service.refresh(original['refresh_token'])
            except Denied:return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(rotate,range(2)))
        self.assertEqual(sum(x is not None for x in results),1)
        # The losing replay revokes the winning session after both transactions finish.
        with self.assertRaises(Denied):self.service.identity(next(x for x in results if x)['access_token'])

    def test_deletion_revokes_sessions_and_blocks_new_login(self):
        subject = 'synthetic-delete-' + str(uuid4())
        session = self.login(subject)
        tenant = self.service.identity(session['access_token'])['tenant_id']
        with tenant_transaction(self.api_pool,tenant) as conn:conn.execute('SELECT ops.begin_deletion()')
        with self.assertRaises(Denied):self.service.identity(session['access_token'])
        with self.assertRaises(Denied):self.service.refresh(session['refresh_token'])
        challenge = self.service.challenge()
        with self.assertRaises(Denied):
            self.service.login(self.proof(challenge,subject),challenge['challenge_id'])
        with connect() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM auth.sessions WHERE account_id=(SELECT account_id FROM private.tenants WHERE id=%s) AND revoked_at IS NULL',(tenant,)).fetchone()[0],0)

    def test_runtime_roles_cannot_read_or_write_session_tables(self):
        for role in ('cb_auth','cb_api','cb_global_worker','cb_private_worker','cb_privacy'):
            with self.subTest(role=role),connect(role) as conn:
                for statement in ('SELECT * FROM auth.sessions','SELECT * FROM auth.challenges',
                                  'SELECT * FROM auth.used_refresh'):
                    with self.assertRaises(psycopg.errors.InsufficientPrivilege):conn.execute(statement)

    def test_http_boundary_rejects_cross_user_and_bad_tokens(self):
        status, challenge = self.request('POST','/v1/auth/challenges')
        self.assertEqual(status,'200 OK')
        status, session = self.request('POST','/v1/auth/google',
                                       {'id_token':self.proof(challenge),'challenge_id':challenge['challenge_id']})
        self.assertEqual(status,'200 OK')
        self.assertEqual(self.request('GET','/v1/me')[0],'401 Unauthorized')
        self.assertEqual(self.request('GET','/v1/me',access='invalid')[0],'401 Unauthorized')
        self.assertEqual(self.request('GET','/v1/me',access=session['access_token'])[0],'200 OK')
        self.assertEqual(self.request('POST','/v1/auth/google',{'id_token':'x','challenge_id':challenge['challenge_id'],'tenant_id':'other'})[0],'400 Bad Request')
        self.assertEqual(self.request('POST','/v1/auth/logout',access=session['access_token'])[0],'204 No Content')
        self.assertEqual(self.request('GET','/v1/me',access=session['access_token'])[0],'401 Unauthorized')


if __name__ == '__main__':
    unittest.main(verbosity=2)
