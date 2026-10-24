"""Small WSGI boundary for the V1 identity routes; no deployment side effects."""
from __future__ import annotations

import json
import re
from urllib.parse import parse_qsl
from uuid import uuid4

import psycopg

from .auth import Denied
from .ingestion import IngestionFailure
from .resume import MAX_BYTES, ResumeRejected
from tools.contracts import ContractError, strict_load
from .mobile import Conflict
from .tts import TtsUnavailable


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


class ResumeAPI:
    """Authenticated multipart boundary; document bytes never enter request logs or SQL."""
    def __init__(self, identity: IdentityAPI, service):
        self.identity, self.service = identity, service

    def __call__(self, environ, start_response):
        method, path = environ.get('REQUEST_METHOD'), environ.get('PATH_INFO', '')
        try:
            token = IdentityAPI._bearer(environ)
            principal = self.identity.service.identity(token)
            if method == 'POST' and path == '/v1/me/resume':
                metadata, document = self._multipart(environ)
                key = environ.get('HTTP_IDEMPOTENCY_KEY', '')
                if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}', key):
                    raise ResumeRejected('invalid idempotency key')
                output = self.service.upload(principal['tenant_id'], metadata, document, key)
                status = '202 Accepted'
            elif method == 'GET' and path == '/v1/me/jobs/latest':
                output = self.service.latest_status(principal['tenant_id'])
                if output is None:
                    return self._respond(start_response, '410 Gone', IdentityAPI._error('410 Gone', 'RESOURCE_GONE')[1])
                status = '200 OK'
            elif method == 'GET' and path.startswith('/v1/me/jobs/'):
                output = self.service.status(principal['tenant_id'], path.removeprefix('/v1/me/jobs/'))
                if output is None:
                    return self._respond(start_response, '410 Gone', IdentityAPI._error('410 Gone', 'RESOURCE_GONE')[1])
                status = '200 OK'
            elif method == 'DELETE' and path.startswith('/v1/me/jobs/'):
                output = {'cancelled': self.service.cancel(principal['tenant_id'], path.removeprefix('/v1/me/jobs/'))}
                status = '200 OK' if output['cancelled'] else '410 Gone'
            else:
                return self._respond(start_response, '404 Not Found', IdentityAPI._error('404 Not Found', 'RESOURCE_GONE')[1])
        except Denied:
            return self._respond(start_response, '401 Unauthorized', IdentityAPI._error('401 Unauthorized', 'UNAUTHENTICATED')[1])
        except PayloadTooLarge:
            return self._respond(start_response, '413 Content Too Large', IdentityAPI._error('413 Content Too Large', 'PAYLOAD_TOO_LARGE')[1])
        except (ResumeRejected, ContractError, ValueError, KeyError, TypeError):
            return self._respond(start_response, '422 Unprocessable Content', IdentityAPI._error('422 Unprocessable Content', 'SCHEMA_INVALID')[1])
        except psycopg.Error:
            return self._respond(start_response, '503 Service Unavailable', IdentityAPI._error('503 Service Unavailable', 'UNAVAILABLE')[1])
        return self._respond(start_response, status, output)

    @staticmethod
    def _respond(start_response, status, output):
        body = json.dumps(output, separators=(',', ':')).encode()
        start_response(status, [('Content-Type', 'application/json'), ('Content-Length', str(len(body))),
                                ('Cache-Control', 'no-store')])
        return [body]

    @staticmethod
    def _multipart(request):
        length = request.get('CONTENT_LENGTH', '')
        if not length.isdecimal():
            raise ResumeRejected('invalid body length')
        if int(length) > MAX_BYTES + 20_000:
            raise PayloadTooLarge()
        content_type = request.get('CONTENT_TYPE', '')
        match = re.fullmatch(r'multipart/form-data;\s*boundary=([A-Za-z0-9._-]{1,70})', content_type)
        if not match:
            raise ResumeRejected('invalid multipart type')
        raw = request['wsgi.input'].read(int(length))
        if len(raw) != int(length):
            raise ResumeRejected('short body')
        boundary = b'--' + match.group(1).encode('ascii')
        fields = {}
        for section in raw.split(boundary)[1:-1]:
            if not section.startswith(b'\r\n') or not section.endswith(b'\r\n'):
                raise ResumeRejected('malformed multipart')
            headers, separator, value = section[2:-2].partition(b'\r\n\r\n')
            if not separator:
                raise ResumeRejected('malformed part')
            line = headers.decode('ascii', 'strict').split('\r\n')
            if len(line) not in (1, 2) or not line[0].startswith('Content-Disposition: form-data; name="'):
                raise ResumeRejected('invalid part headers')
            name = line[0].removeprefix('Content-Disposition: form-data; name="').split('"', 1)[0]
            if name not in {'metadata', 'file'} or name in fields:
                raise ResumeRejected('invalid fields')
            fields[name] = value
        if set(fields) != {'metadata', 'file'}:
            raise ResumeRejected('missing multipart fields')
        return strict_load(fields['metadata']), fields['file']


class CareerBrainAPI:
    """Route producer traffic separately from user identity traffic."""

    def __init__(self, identity: IdentityAPI, ingestion, resume=None, mobile=None, tts=None):
        self.identity, self.ingestion = identity, ingestion
        self.resume = None if resume is None else ResumeAPI(identity, resume)
        self.mobile, self.tts = mobile, tts

    def close(self):
        self.ingestion.pool.close()
        if self.resume is not None:
            self.resume.service.worker_pool.close()
        if self.mobile is not None:
            self.mobile.pool.close()
        self.identity.close()

    def __call__(self, environ, start_response):
        method, path = environ.get('REQUEST_METHOD'), environ.get('PATH_INFO', '')
        if self.mobile is not None and (path == '/v1/recommendations' or path.startswith('/v1/recommendations/')
                                       or path == '/v1/applications' or path == '/v1/notifications/tts' or path.startswith('/v1/deletions/')):
            return self._mobile(environ, start_response)
        if path == '/v1/me/resume' or path.startswith('/v1/me/jobs/'):
            if self.resume is None:
                return self.identity(environ, start_response)
            return self.resume(environ, start_response)
        if path != '/v1/ingestion/batches' and not path.startswith('/v1/ingestion/batches/'):
            return self.identity(environ, start_response)
        headers = [('Content-Type', 'application/json'), ('Cache-Control', 'no-store')]
        correlation = str(uuid4())
        try:
            token = IdentityAPI._bearer(environ)
            producer = self.ingestion.authenticate(token)
            if method == 'POST' and path == '/v1/ingestion/batches':
                if environ.get('HTTP_CONTENT_ENCODING') or environ.get('CONTENT_ENCODING'):
                    raise IngestionFailure(400, 'SCHEMA_INVALID')
                key = environ.get('HTTP_IDEMPOTENCY_KEY', '')
                if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}', key):
                    raise IngestionFailure(400, 'SCHEMA_INVALID')
                if environ.get('CONTENT_TYPE', '').split(';')[0] != 'application/json':
                    raise IngestionFailure(400, 'SCHEMA_INVALID')
                size = environ.get('CONTENT_LENGTH', '')
                if not size.isdecimal():
                    raise IngestionFailure(400, 'SCHEMA_INVALID')
                if int(size) > 1_048_576:
                    raise IngestionFailure(413, 'PAYLOAD_TOO_LARGE')
                raw = environ['wsgi.input'].read(int(size))
                if len(raw) != int(size):
                    raise IngestionFailure(400, 'SCHEMA_INVALID')
                value = self.ingestion.decode(raw, key)
                output, replay = self.ingestion.submit(producer, value)
                if output['schema_version'] == 'careerbrain.error.v1':
                    status = ('403 Forbidden' if output['code'] == 'SOURCE_NOT_AUTHORIZED'
                              else '409 Conflict' if output['code'] == 'EVENT_CONFLICT'
                              else '422 Unprocessable Content')
                else:
                    status = '202 Accepted'
                if replay:
                    headers.append(('Idempotent-Replay', 'true'))
            elif method == 'GET' and path.startswith('/v1/ingestion/batches/'):
                batch_id = path.removeprefix('/v1/ingestion/batches/')
                if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}', batch_id):
                    raise IngestionFailure(400, 'SCHEMA_INVALID')
                output = self.ingestion.status(producer, batch_id)
                if output is None:
                    raise IngestionFailure(410, 'RESOURCE_GONE')
                status = '200 OK'
            else:
                raise IngestionFailure(404, 'RESOURCE_GONE')
        except Denied:
            failure = IngestionFailure(401, 'UNAUTHENTICATED')
            status, output = '401 Unauthorized', failure.response(correlation)
        except IngestionFailure as failure:
            reason = {400: 'Bad Request', 401: 'Unauthorized', 403: 'Forbidden',
                      404: 'Not Found', 409: 'Conflict', 410: 'Gone',
                      413: 'Content Too Large', 422: 'Unprocessable Content',
                      429: 'Too Many Requests', 503: 'Service Unavailable'}[failure.status]
            status, output = f'{failure.status} {reason}', failure.response(correlation)
            if failure.code == 'BATCH_IN_PROGRESS':
                headers.append(('Retry-After', '1'))
            if failure.code == 'RATE_LIMITED':
                headers.append(('Retry-After', '60'))
        except psycopg.Error:
            status = '503 Service Unavailable'
            output = IngestionFailure(503, 'UNAVAILABLE', retryable=True).response(correlation)
        body = json.dumps(output, separators=(',', ':')).encode()
        headers.append(('Content-Length', str(len(body))))
        start_response(status, headers)
        return [body]

    def _mobile(self, environ, start_response):
        method, path = environ.get('REQUEST_METHOD'), environ.get('PATH_INFO', '')
        headers = [('Content-Type', 'application/json'), ('Cache-Control', 'no-store')]
        try:
            if method == 'GET' and path.startswith('/v1/deletions/'):
                capability = environ.get('HTTP_DELETION_CAPABILITY', '')
                output = self.mobile.receipt(path.removeprefix('/v1/deletions/'), capability)
                status = '200 OK'
            else:
                access = IdentityAPI._bearer(environ)
                principal = self.identity.service.identity(access)
                query = dict(parse_qsl(environ.get('QUERY_STRING', ''), strict_parsing=True))
                limit = int(query.get('limit', '50'))
                if method == 'GET' and path == '/v1/recommendations': output, status = self.mobile.recommendations(principal['tenant_id'], query.get('cursor'), limit), '200 OK'
                elif method == 'GET' and path == '/v1/recommendations/changes': output, status = self.mobile.changes(principal['tenant_id'], query.get('cursor'), limit), '200 OK'
                elif method == 'POST' and path == '/v1/recommendations/ack': self.mobile.ack(principal['tenant_id'], strict_load(self._raw(environ))); output, status = None, '204 No Content'
                elif method == 'PUT' and path == '/v1/applications': self.mobile.application(principal['tenant_id'], strict_load(self._raw(environ))); output, status = None, '204 No Content'
                elif method == 'POST' and path == '/v1/notifications/tts':
                    if self.tts is None:
                        raise TtsUnavailable()
                    audio = self.tts.speak(principal['tenant_id'], strict_load(self._raw(environ)))
                    start_response('200 OK', [('Content-Type', 'audio/mpeg'), ('Content-Length', str(len(audio))), ('Cache-Control', 'no-store')])
                    return [audio]
                elif method == 'DELETE' and path == '/v1/me':
                    request_id = environ.get('HTTP_IDEMPOTENCY_KEY', '')
                    output, status = self.mobile.delete(principal['tenant_id'], request_id), '202 Accepted'
                    headers.append(('Deletion-Capability', output.pop('deletion_capability')))
                else: return self._respond(start_response, '404 Not Found', IdentityAPI._error('404 Not Found', 'RESOURCE_GONE')[1])
        except Denied: return self._respond(start_response, '401 Unauthorized', IdentityAPI._error('401 Unauthorized', 'UNAUTHENTICATED')[1])
        except LookupError: return self._respond(start_response, '410 Gone', IdentityAPI._error('410 Gone', 'RESOURCE_GONE')[1])
        except Conflict: return self._respond(start_response, '409 Conflict', IdentityAPI._error('409 Conflict', 'IDEMPOTENCY_CONFLICT')[1])
        except TtsUnavailable: return self._respond(start_response, '503 Service Unavailable', IdentityAPI._error('503 Service Unavailable', 'UNAVAILABLE')[1])
        except (ContractError, ValueError, KeyError, TypeError): return self._respond(start_response, '422 Unprocessable Content', IdentityAPI._error('422 Unprocessable Content', 'SCHEMA_INVALID')[1])
        except psycopg.Error: return self._respond(start_response, '503 Service Unavailable', IdentityAPI._error('503 Service Unavailable', 'UNAVAILABLE')[1])
        if output is None:
            start_response(status, headers + [('Content-Length', '0')]); return [b'']
        body = json.dumps(output, separators=(',', ':')).encode(); start_response(status, headers + [('Content-Length', str(len(body)))]); return [body]

    @staticmethod
    def _raw(environ):
        size = environ.get('CONTENT_LENGTH', '')
        if not size.isdecimal() or int(size) > 1_048_576 or environ.get('CONTENT_TYPE', '').split(';')[0] != 'application/json': raise ValueError('invalid body')
        raw = environ['wsgi.input'].read(int(size))
        if len(raw) != int(size): raise ValueError('short body')
        return raw

    @staticmethod
    def _respond(start_response, status, output):
        body = json.dumps(output, separators=(',', ':')).encode(); start_response(status, [('Content-Type', 'application/json'), ('Content-Length', str(len(body))), ('Cache-Control', 'no-store')]); return [body]
