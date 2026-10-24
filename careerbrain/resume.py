"""Ephemeral synthetic-PDF resume processing; no raw document reaches PostgreSQL."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import os
import re
import resource
import subprocess
import sys
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from tools.contracts import ContractError, validate, validate_evidence


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


class FilesystemResumeStore:
    """Shared tmpfs-only store; PostgreSQL receives only its opaque handle."""
    def __init__(self, directory: str):
        self.directory = os.path.realpath(directory)
        if not os.path.isdir(self.directory) or os.path.islink(self.directory):
            raise RuntimeError('invalid ephemeral resume directory')

    def _path(self, handle: UUID) -> str:
        return os.path.join(self.directory, str(handle))

    def put(self, document: bytes, expires_at: datetime) -> UUID:
        handle = uuid4(); path = self._path(handle)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
        fd = os.open(path, flags, 0o600)
        try:
            with os.fdopen(fd, 'wb') as target:
                target.write(document); target.flush(); os.fsync(target.fileno())
        except BaseException:
            try: os.unlink(path)
            except FileNotFoundError: pass
            raise
        return handle

    def get(self, handle: UUID, now: datetime | None = None) -> bytes:
        try:
            with open(self._path(handle), 'rb', opener=lambda path, flags: os.open(path, flags | getattr(os, 'O_NOFOLLOW', 0))) as source:
                value = source.read(MAX_BYTES + 1)
        except FileNotFoundError as error:
            raise TemporaryMissing('temporary content unavailable') from error
        if len(value) > MAX_BYTES: raise ResumeRejected('invalid size')
        return value

    def delete(self, handle: UUID) -> None:
        try: os.unlink(self._path(handle))
        except FileNotFoundError: pass

    def reap(self, now: datetime | None = None) -> int:
        now = now or datetime.now(timezone.utc); removed = 0
        for name in os.listdir(self.directory):
            try:
                handle = UUID(name); age = datetime.fromtimestamp(os.stat(self._path(handle), follow_symlinks=False).st_mtime, timezone.utc)
                if age + TTL <= now: self.delete(handle); removed += 1
            except (ValueError, FileNotFoundError): continue
        return removed


def assert_ephemeral_runtime() -> None:
    """CI proof of process limits only; deployment proof remains a separate gate."""
    soft, hard = resource.getrlimit(resource.RLIMIT_CORE)
    if soft != 0 or hard != 0:
        raise RuntimeError('core dumps are not disabled')
    try:
        with open('/proc/swaps', encoding='ascii') as source:
            swaps = source.read().splitlines()
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



class BoundedPdfExtractor(DeterministicPdfExtractor):
    """Extract ordinary PDF text in a time- and memory-bounded child process.

    The strict synthetic fixture parser remains available only when explicitly
    passed to ResumeService in disposable tests.
    """
    version = 'pypdf-text-bounded-v1'

    def extract(self, document: bytes) -> str:
        if not isinstance(document, bytes) or not 1 <= len(document) <= MAX_BYTES:
            raise ResumeRejected('invalid size')
        if not document.startswith(b'%PDF-') or b'%%EOF' not in document[-2048:]:
            raise ResumeRejected('invalid pdf')
        if any(token in document for token in self.forbidden):
            raise ResumeRejected('active or encrypted pdf')
        try:
            result = subprocess.run(
                [sys.executable, '-m', 'careerbrain.pdf_text'],
                input=document, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                timeout=12, check=False)
            if result.returncode != 0 or len(result.stdout) > MAX_TEXT * 4:
                raise ResumeRejected('unsupported pdf or extraction limit')
            text = result.stdout.decode('utf-8', 'strict')
            if len(text) > MAX_TEXT:
                raise ResumeRejected('too much text')
            return text
        except (subprocess.TimeoutExpired, UnicodeDecodeError, OSError) as error:
            raise ResumeRejected('unsupported pdf or extraction limit') from error



class ResumeService:
    extractor_version = 'deterministic-pdf-v1'
    taxonomy_version = 'professional-v1'

    def __init__(self, api_pool, worker_pool, store: EphemeralResumeStore | FilesystemResumeStore, extractor=None):
        self.api_pool, self.worker_pool, self.store = api_pool, worker_pool, store
        self.extractor = extractor or DeterministicPdfExtractor()
        self.extractor_version = getattr(self.extractor, 'version', self.extractor_version)
        for pool, role in ((api_pool, 'cb_api'), (worker_pool, 'cb_private_worker')):
            if pool is None: continue
            with pool.connection() as conn:
                if conn.execute('SELECT current_user').fetchone()[0] != role:
                    raise ValueError('Runtime database role mismatch')

    def upload(self, tenant_id: str, metadata: dict, document: bytes, idempotency_key: str) -> dict:
        if self.api_pool is None: raise RuntimeError('upload unavailable in worker')
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
            text = self.extractor.extract(document)
            status, attributes = self.extractor.profile(document)
            profile = {'schema_version': 'careerbrain.profile.v2',
                     'tenant_id': str(claim.tenant_id), 'profile_version': 1,
                     'generation': claim.generation, 'status': status, 'attributes': attributes,
                     'extractor_version': self.extractor_version,
                     'taxonomy_version': self.taxonomy_version}
            validate('private-profile-v2', profile)
            validate_evidence(text, profile, schema='private-profile-v2')
            result = self._call('private.complete_resume_job', claim, status, Jsonb(attributes),
                                self.extractor_version, self.taxonomy_version)
        except (ResumeRejected, ContractError):
            result = self._call('private.fail_resume_job', claim, False)
        except Exception:
            result = self._call('private.fail_resume_job', claim, True)
        if result != 'RETRY':
            self.store.delete(claim.handle)
        if result in ('READY', 'UNCERTAIN'):
            self._schedule_matches(claim.tenant_id)
        return result

    def _schedule_matches(self, tenant_id: UUID) -> None:
        """Profile completion queues every classified event under tenant RLS."""
        with self.worker_pool.connection() as conn, conn.transaction():
            conn.execute("SELECT set_config('careerbrain.tenant_id',%s,true)", (str(tenant_id),))
            try:
                with conn.transaction():
                    events = conn.execute('SELECT event_id FROM catalog.current_classifications').fetchall()
            except psycopg.errors.InsufficientPrivilege:
                # Pre-011 disposable schemas have no matching projection yet.
                return
            for (event_id,) in events:
                conn.execute('SELECT private.create_match_job(%s)', (event_id,))

    def cancel(self, tenant_id: str, job_id: str) -> bool:
        if self.api_pool is None: raise RuntimeError('cancel unavailable in worker')
        with self.api_pool.connection() as conn, conn.transaction():
            conn.execute("SELECT set_config('careerbrain.tenant_id',%s,true)", (str(UUID(tenant_id)),))
            handle = conn.execute('SELECT private.cancel_resume_job(%s)', (UUID(job_id),)).fetchone()[0]
        if handle is None:
            return False
        self.store.delete(handle)
        return True

    def latest_status(self, tenant_id: str) -> dict | None:
        """Return only the authenticated tenant's most recent resume job."""
        if self.api_pool is None: raise RuntimeError('status unavailable in worker')
        with self.api_pool.connection() as conn, conn.transaction():
            conn.execute("SELECT set_config('careerbrain.tenant_id',%s,true)", (str(UUID(tenant_id)),))
            row = conn.execute(
                "SELECT id FROM queue.private_jobs WHERE tenant_id=%s AND kind='RESUME' "
                "ORDER BY created_at DESC,id DESC LIMIT 1",
                (UUID(tenant_id),)
            ).fetchone()
            if row is None:
                return None
            state = conn.execute('SELECT private.resume_job_status(%s)', (row[0],)).fetchone()[0]
        return None if state is None else {'job_id': str(row[0]), 'status': state}

    def status(self, tenant_id: str, job_id: str) -> dict | None:
        if self.api_pool is None: raise RuntimeError('status unavailable in worker')
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
