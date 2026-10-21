"""Google proof verification and opaque, database-revocable user sessions."""
from __future__ import annotations

from datetime import timezone
import hashlib
import hmac
import re
import secrets
import time
from uuid import UUID, uuid4

import jwt
import psycopg
from jwt import PyJWKClient

GOOGLE_KEYS = 'https://www.googleapis.com/oauth2/v3/certs'
ISSUERS = ('https://accounts.google.com', 'accounts.google.com')
CLIENT_ID = re.compile(r'^[A-Za-z0-9_-]+\.apps\.googleusercontent\.com$')


class Denied(Exception):
    """Untrusted or expired proof; never include submitted token in the message."""


def digest(value: str) -> str:
    return hashlib.sha256(value.encode('ascii')).hexdigest()


class GoogleVerifier:
    def __init__(self, web_client_id: str, presenter_ids: tuple[str, ...], *, key_provider=None):
        if not CLIENT_ID.fullmatch(web_client_id) or not presenter_ids or any(
                not CLIENT_ID.fullmatch(client) for client in presenter_ids):
            raise ValueError('Approved OAuth audience and presenter IDs are required')
        self.audience = web_client_id
        self.presenters = frozenset(presenter_ids)
        # The production key URL is fixed in code; JWT headers never choose a host.
        self.key_provider = key_provider or PyJWKClient(GOOGLE_KEYS, cache_jwk_set=True,
                                                       lifespan=300).get_signing_key_from_jwt

    def verify(self, token: str, nonce: str) -> str:
        if not isinstance(token, str) or not 1 <= len(token) <= 16384 or not isinstance(nonce, str):
            raise Denied()
        try:
            header = jwt.get_unverified_header(token)
            if (header.get('alg') != 'RS256' or not isinstance(header.get('kid'), str)
                    or not 1 <= len(header['kid']) <= 128 or any(
                        field in header for field in ('jku', 'x5u', 'jwk', 'x5c'))):
                raise Denied()
            key = self.key_provider(token)
            claims = jwt.decode(token, getattr(key, 'key', key), algorithms=['RS256'],
                                audience=self.audience, issuer=ISSUERS, leeway=30,
                                options={'require': ['iss', 'aud', 'sub', 'iat', 'exp', 'nonce']})
            now = int(time.time())
            subject = claims['sub']
            if (claims['aud'] != self.audience or not isinstance(subject, str)
                    or not 1 <= len(subject) <= 255 or not subject.isascii()
                    or any(ord(c) < 33 or ord(c) > 126 for c in subject)
                    or type(claims['iat']) is not int or type(claims['exp']) is not int
                    or claims['iat'] > now + 30 or claims['exp'] <= now - 30
                    or not isinstance(claims['nonce'], str)
                    or not hmac.compare_digest(claims['nonce'], nonce)
                    or ('azp' in claims and claims['azp'] not in self.presenters)):
                raise Denied()
            return subject
        except (jwt.PyJWTError, ValueError, KeyError, TypeError, OverflowError) as error:
            raise Denied() from error


class AuthService:
    def __init__(self, auth_pool, api_pool, verifier: GoogleVerifier):
        self.auth_pool = auth_pool
        self.api_pool = api_pool
        self.verifier = verifier
        # A wrong SQL role must fail at startup instead of getting owner privileges.
        for pool, expected in ((auth_pool, 'cb_auth'), (api_pool, 'cb_api')):
            with pool.connection() as conn:
                if conn.execute('SELECT current_user').fetchone()[0] != expected:
                    raise ValueError('Runtime database role mismatch')

    def challenge(self) -> dict:
        challenge_id = uuid4()
        nonce = secrets.token_urlsafe(32)
        with self.auth_pool.connection() as conn, conn.transaction():
            conn.execute('SELECT auth.issue_challenge(%s,%s)', (challenge_id, digest(nonce)))
        return {'challenge_id': str(challenge_id), 'nonce': nonce, 'expires_in': 300}

    @staticmethod
    def _tokens() -> tuple[str, str]:
        return secrets.token_urlsafe(32), secrets.token_urlsafe(32)

    @staticmethod
    def _response(access: str, refresh: str) -> dict:
        return {'schema_version': 'careerbrain.session.v1', 'access_token': access,
                'refresh_token': refresh, 'token_type': 'Bearer', 'expires_in': 900}

    def login(self, token: str, challenge_id: str) -> dict:
        try:
            challenge = UUID(challenge_id)
        except (ValueError, TypeError, AttributeError) as error:
            raise Denied() from error
        # Read the nonce through a restricted function only; its hash is the DB proof.
        # The original nonce is supplied by the client in the signed token claim.
        # Verification precedes atomic consumption/provisioning/session issuance.
        try:
            nonce = jwt.decode(token, options={'verify_signature': False},
                               algorithms=['RS256']).get('nonce')
        except (jwt.PyJWTError, ValueError, TypeError) as error:
            raise Denied() from error
        if not isinstance(nonce, str) or not 32 <= len(nonce) <= 128:
            raise Denied()
        subject = self.verifier.verify(token, nonce)
        access, refresh = self._tokens()
        try:
            with self.auth_pool.connection() as conn, conn.transaction():
                used = conn.execute('SELECT auth.consume_challenge(%s,%s)',
                                    (challenge, digest(nonce))).fetchone()[0]
                if not used:
                    raise Denied()
                account = conn.execute('SELECT user_id FROM identity.provision(%s,%s)',
                                       ('https://accounts.google.com', subject)).fetchone()[0]
                conn.execute('SELECT auth.issue_session(%s,%s,%s)',
                             (account, digest(access), digest(refresh)))
        except psycopg.errors.InsufficientPrivilege as error:
            raise Denied() from error
        return self._response(access, refresh)

    def refresh(self, refresh: str) -> dict:
        if not isinstance(refresh, str) or not 1 <= len(refresh) <= 4096 or not refresh.isascii():
            raise Denied()
        access, next_refresh = self._tokens()
        with self.auth_pool.connection() as conn, conn.transaction():
            outcome = conn.execute('SELECT auth.rotate_session(%s,%s,%s)',
                                   (digest(refresh), digest(access), digest(next_refresh))).fetchone()[0]
        # REPLAY must commit the family revocation before returning an error.
        if outcome != 'OK':
            raise Denied()
        return self._response(access, next_refresh)

    def identity(self, access: str) -> dict:
        if not isinstance(access, str) or not 1 <= len(access) <= 4096 or not access.isascii():
            raise Denied()
        with self.api_pool.connection() as conn, conn.transaction():
            row = conn.execute('SELECT * FROM auth.resolve_access(%s)',
                               (digest(access),)).fetchone()
        if row is None:
            raise Denied()
        return {'schema_version': 'careerbrain.identity.v1', 'user_id': str(row[0]),
                'tenant_id': str(row[1]), 'issuer': row[2], 'subject': row[3],
                'account_created_at': row[4].astimezone(timezone.utc).isoformat().replace('+00:00','Z'),
                'state': row[5], 'profile_status': row[6]}

    def logout(self, access: str) -> None:
        if not isinstance(access, str) or not 1 <= len(access) <= 4096 or not access.isascii():
            raise Denied()
        with self.api_pool.connection() as conn, conn.transaction():
            if not conn.execute('SELECT auth.revoke_access(%s)', (digest(access),)).fetchone()[0]:
                raise Denied()
