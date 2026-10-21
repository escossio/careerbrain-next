"""Ephemeral synthetic-PDF resume processing; no raw document reaches PostgreSQL."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import os
import re
import resource
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from tools.contracts import ContractError, validate


MAX_BYTES = 5 * 1024 * 1024
MAX_PAGES = 50
MAX_TEXT = 200_000
TTL = timedelta(minutes=15)


class ResumeRejected(ValueError):
    """A stable failure category; document content must never be surfaced."""


class TemporaryMissing(ResumeRejected):
    pass


@dataclass(frozen=True)
class ResumeClaim:
    job_id: UUID
    tenant_id: UUID
    handle: UUID
    generation: int
    deletion_epoch: int
    expires_at: datetime
    owner: UUID
    fencing: int


@dataclass
class _Entry:
    document: bytes
    expires_at: datetime


class EphemeralResumeStore:
    """Process-memory test store. Production must prove its separately configured tmpfs boundary."""
    def __init__(self):
        self._entries: dict[UUID, _Entry] = {}

    def put(self, document: bytes, expires_at: datetime) -> UUID:
        handle = uuid4()
        self._entries[handle] = _Entry(bytes(document), expires_at)
        return handle

    def get(self, handle: UUID, now: datetime | None = None) -> bytes:
        self.reap(now)
        entry = self._entries.get(handle)
        if entry is None:
            raise TemporaryMissing('temporary content unavailable')
        return entry.document

    def delete(self, handle: UUID) -> None:
        self._entries.pop(handle, None)

    def reap(self, now: datetime | None = None) -> int:
        now = now or datetime.now(timezone.utc)
        expired = [key for key, entry in self._entries.items() if entry.expires_at <= now]
        for key in expired:
            del self._entries[key]
        return len(expired)

    def __contains__(self, handle: UUID) -> bool:
        return handle in self._entries


def assert_ephemeral_runtime() -> None:
    """CI proof of process limits only; deployment proof remains a separate gate."""
    soft, hard = resource.getrlimit(resource.RLIMIT_CORE)
    if soft != 0 or hard != 0:
        raise RuntimeError('core dumps are not disabled')
    try:
        swaps = open('/proc/swaps', encoding='ascii').read().splitlines()
    except OSError as error:
        raise RuntimeError('swap state unavailable') from error
    if len(swaps) > 1:
        raise RuntimeError('swap is enabled in this runtime')
    if not os.environ.get('NEXT_DISPOSABLE_CI'):
        raise RuntimeError('ephemeral runtime proof is limited to isolated CI')


class DeterministicPdfExtractor:
    """Constrained parser for synthetic fixtures, never a general-purpose PDF renderer."""
    forbidden = (b'/Encrypt', b'/JavaScript', b'/JS', b'/OpenAction', b'/Launch', b'/RichMedia', b'/EmbeddedFile')
    patterns = (('skill', 'instalações elétricas'), ('skill', 'Python'), ('activity', 'enfermagem'),
                ('activity', 'atendimento ao cliente'))

    def extract(self, document: bytes) -> str:
        if not isinstance(document, bytes) or not 1 <= len(document) <= MAX_BYTES:
            raise ResumeRejected('invalid size')
        if not document.startswith(b'%PDF-') or b'%%EOF' not in document[-2048:]:
            raise ResumeRejected('invalid pdf')
        if any(token in document for token in self.forbidden):
            raise ResumeRejected('active or encrypted pdf')
        pages = len(re.findall(rb'/Type\s*/Page(?!s)', document))
        if pages > MAX_PAGES:
            raise ResumeRejected('too many pages')
        fragments = re.findall(rb'\(([^()]*)\)\s*Tj', document)
        try:
            text = ''.join(part.decode('utf-8') for part in fragments)
        except UnicodeDecodeError as error:
            raise ResumeRejected('invalid text') from error
        if len(text) > MAX_TEXT:
            raise ResumeRejected('too much text')
        return text

    def profile(self, document: bytes) -> tuple[str, list[dict]]:
        text = self.extract(document)
        attributes = []
        for name, phrase in self.patterns:
            match = re.search(re.escape(phrase), text, re.IGNORECASE)
            if match:
                attributes.append({'name': name, 'value': match.group(0), 'basis': 'explicit',
                                   'confidence': 1, 'evidence': [{'field': 'resume', 'quote': match.group(0),
                                                                   'start': match.start(), 'end': match.end()}]})
        return ('READY', attributes) if attributes else ('UNCERTAIN', [])


class ResumeService:
    extractor_version = 'deterministic-pdf-v1'
    taxonomy_version = 'professional-v1'

    def __init__(self, api_pool, worker_pool, store: EphemeralResumeStore, extractor=None):
        self.api_pool, self.worker_pool, self.store = api_pool, worker_pool, store
        self.extractor = extractor or DeterministicPdfExtractor()
        for pool, role in ((api_pool, 'cb_api'), (worker_pool, 'cb_private_worker')):
            with pool.connection() as conn:
                if conn.execute('SELECT current_user').fetchone()[0] != role:
                    raise ValueError('Runtime database role mismatch')

    def upload(self, tenant_id: str, metadata: dict, document: bytes, idempotency_key: str) -> dict:
        validate('resume-upload', metadata)
        if metadata['request_id'] != idempotency_key or metadata['content_length'] != len(document):
            raise ResumeRejected('invalid upload envelope')
        # Verify before retaining even process-memory bytes.
        self.extractor.extract(document)
        expires = datetime.now(timezone.utc) + TTL
        handle = self.store.put(document, expires)
        try:
            with self.api_pool.connection() as conn, conn.transaction():
                conn.execute("SELECT set_config('careerbrain.tenant_id',%s,true)", (str(UUID(tenant_id)),))
                row = conn.execute('SELECT * FROM private.create_resume_job(%s,%s)',
                                   (metadata['request_id'], handle)).fetchone()
            job, _, _, _, replayed = row
            if replayed:
                self.store.delete(handle)
            return {'job_id': str(job), 'status': 'PENDING'}
        except Exception:
            self.store.delete(handle)
            raise

    def claim(self) -> ResumeClaim | None:
        owner = uuid4()
        with self.worker_pool.connection() as conn, conn.transaction():
            row = conn.execute('SELECT * FROM private.claim_resume_job(%s)', (owner,)).fetchone()
        return None if row is None else ResumeClaim(*row[:6], owner, row[6])

    def _call(self, function: str, claim: ResumeClaim, *extra):
        with self.worker_pool.connection() as conn, conn.transaction():
            return conn.execute(f'SELECT {function}(%s,%s,%s' + ',%s' * len(extra) + ')',
                                (claim.job_id, claim.owner, claim.fencing, *extra)).fetchone()[0]

    def process_once(self) -> str | None:
        claim = self.claim()
        if claim is None:
            return None
        try:
            document = self.store.get(claim.handle)
        except TemporaryMissing:
            result = self._call('private.expire_resume_job', claim)
            self.store.delete(claim.handle)
            return 'EXPIRED' if result else 'FENCED'
        try:
            status, attributes = self.extractor.profile(document)
            result = self._call('private.complete_resume_job', claim, status, Jsonb(attributes),
                                self.extractor_version, self.taxonomy_version)
        except ResumeRejected:
            result = self._call('private.fail_resume_job', claim, False)
        except Exception:
            result = self._call('private.fail_resume_job', claim, True)
        if result != 'RETRY':
            self.store.delete(claim.handle)
        return result

    def cancel(self, tenant_id: str, job_id: str) -> bool:
        with self.api_pool.connection() as conn, conn.transaction():
            conn.execute("SELECT set_config('careerbrain.tenant_id',%s,true)", (str(UUID(tenant_id)),))
            handle = conn.execute('SELECT private.cancel_resume_job(%s)', (UUID(job_id),)).fetchone()[0]
        if handle is None:
            return False
        self.store.delete(handle)
        return True

    def status(self, tenant_id: str, job_id: str) -> dict | None:
        with self.api_pool.connection() as conn, conn.transaction():
            conn.execute("SELECT set_config('careerbrain.tenant_id',%s,true)", (str(UUID(tenant_id)),))
            state = conn.execute('SELECT private.resume_job_status(%s)', (UUID(job_id),)).fetchone()[0]
        return None if state is None else {'job_id': job_id, 'status': state}

    def sweep(self) -> int:
        with self.worker_pool.connection() as conn, conn.transaction():
            handles = [row[0] for row in conn.execute('SELECT * FROM private.reap_expired_resume_handles()')]
        for handle in handles:
            self.store.delete(handle)
        return len(handles) + self.store.reap()
