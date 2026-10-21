"""Small WSGI boundary for the V1 identity routes; no deployment side effects."""
from __future__ import annotations

import json
from uuid import uuid4

import psycopg

from .auth import Denied


class PayloadTooLarge(ValueError):
    pass


class IdentityAPI:
    def __init__(self, service):
        self.service = service

    def close(self):
        self.service.auth_pool.close()
        self.service.api_pool.close()

    def __call__(self, environ, start_response):
        status, output = self.dispatch(environ)
        body = b'' if output is None else json.dumps(output, separators=(',', ':')).encode()
        start_response(status, [('Content-Type', 'application/json'),
                                ('Content-Length', str(len(body))),
                                ('Cache-Control', 'no-store')])
        return [body]

    def dispatch(self, request):
        method, path = request.get('REQUEST_METHOD'), request.get('PATH_INFO')
        routes = {('POST', '/v1/auth/challenges'), ('POST', '/v1/auth/google'),
                  ('POST', '/v1/auth/refresh'), ('POST', '/v1/auth/logout'),
                  ('GET', '/v1/me')}
        if (method, path) not in routes:
            return self._error('404 Not Found', 'RESOURCE_GONE')
        try:
            if (method, path) == ('POST', '/v1/auth/challenges'):
                self._body(request, empty=True)
                return '200 OK', self.service.challenge()
            if (method, path) == ('POST', '/v1/auth/google'):
                data = self._body(request, fields={'id_token': 16384, 'challenge_id': 128})
                return '200 OK', self.service.login(data['id_token'], data['challenge_id'])
            if (method, path) == ('POST', '/v1/auth/refresh'):
                data = self._body(request, fields={'refresh_token': 4096})
                return '200 OK', self.service.refresh(data['refresh_token'])
            access = self._bearer(request)
            if (method, path) == ('POST', '/v1/auth/logout'):
                self._body(request, empty=True)
                self.service.logout(access)
                return '204 No Content', None
            return '200 OK', self.service.identity(access)
        except Denied:
            return self._error('401 Unauthorized', 'UNAUTHENTICATED')
        except PayloadTooLarge:
            return self._error('413 Content Too Large', 'PAYLOAD_TOO_LARGE')
        except (ValueError, KeyError, TypeError):
            return self._error('400 Bad Request', 'SCHEMA_INVALID')
        except psycopg.Error:
            return self._error('503 Service Unavailable', 'UNAVAILABLE')

    @staticmethod
    def _bearer(request):
        value = request.get('HTTP_AUTHORIZATION', '')
        if not value.startswith('Bearer ') or len(value) > 4103:
            raise Denied()
        token = value[7:]
        if not token or ' ' in token:
            raise Denied()
        return token

    @staticmethod
    def _body(request, *, fields=None, empty=False):
        raw_length = request.get('CONTENT_LENGTH', '')
        if raw_length == '':
            raw_length = '0'
        if not raw_length.isdecimal():
            raise ValueError('Invalid request size')
        if int(raw_length) > 20000:
            raise PayloadTooLarge()
        length = int(raw_length)
        if length and request.get('CONTENT_TYPE', '').split(';')[0] != 'application/json':
            raise ValueError('Invalid content type')
        data = request['wsgi.input'].read(length)
        if len(data) != length:
            raise ValueError('Short body')
        if empty:
            if data not in (b'', b'{}'):
                raise ValueError('Unexpected body')
            return {}
        payload = json.loads(data)
        if not isinstance(payload, dict) or set(payload) != set(fields):
            raise ValueError('Invalid fields')
        for name, maximum in fields.items():
            value = payload[name]
            if not isinstance(value, str) or not 1 <= len(value) <= maximum:
                raise ValueError('Invalid field')
        return payload

    @staticmethod
    def _error(status, code):
        return status, {'schema_version': 'careerbrain.error.v1',
                        'correlation_id': str(uuid4()), 'code': code,
                        'retryable': False, 'items': []}
