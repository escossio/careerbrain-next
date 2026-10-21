"""Transactional, producer-authenticated ingestion of approved synthetic or licensed facts."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from tools.contracts import ContractError, digest, instant, strict_load, validate

ROUTE = 'careerbrain.ingestion.v1'


class IngestionFailure(Exception):
    def __init__(self, status: int, code: str, *, index: int | None = None,
                 field: str = '', retryable: bool = False):
        self.status, self.code, self.index, self.field, self.retryable = (
            status, code, index, field, retryable)

    def response(self, correlation: str) -> dict:
        items = [] if self.index is None else [dict(index=self.index, field=self.field or 'record', code=self.code)]
        return dict(schema_version='careerbrain.error.v1', correlation_id=correlation,
                    code=self.code, retryable=self.retryable, items=items)


def uid(value: str) -> UUID:
    try:
        return UUID(value)
    except (ValueError, TypeError, AttributeError) as error:
        raise IngestionFailure(422, 'SCHEMA_INVALID') from error


def timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


class IngestionService:
    def __init__(self, pool):
        self.pool = pool
        with pool.connection() as conn:
            if conn.execute('SELECT current_user').fetchone()[0] != 'cb_ingest':
                raise ValueError('Runtime database role mismatch')

    def authenticate(self, token: str) -> UUID:
        if not isinstance(token, str) or not 32 <= len(token) <= 4096 or not token.isascii():
            raise IngestionFailure(401, 'UNAUTHENTICATED')
        hashed = hashlib.sha256(token.encode('ascii')).hexdigest()
        with self.pool.connection() as conn:
            row = conn.execute('SELECT catalog.authenticate_producer(%s)', (hashed,)).fetchone()
        if row is None or row[0] is None:
            raise IngestionFailure(401, 'UNAUTHENTICATED')
        return row[0]

    @staticmethod
    def decode(raw: bytes, key: str) -> dict:
        try:
            value = strict_load(raw)
            validate('ingestion-batch', value)
        except ContractError as error:
            status = 413 if error.code == 'PAYLOAD_TOO_LARGE' else 422
            raise IngestionFailure(status, error.code) from error
        if key != value['batch_id']:
            raise IngestionFailure(400, 'SCHEMA_INVALID')
        return value

    def submit(self, producer: UUID, value: dict, *, fault: str | None = None) -> tuple[dict, bool]:
        batch_id = value['batch_id']
        hashed = digest(value)
        correlation = str(uuid4())
        with self.pool.connection() as limiter:
            with limiter.transaction():
                attempts = limiter.execute('''INSERT INTO ops.producer_rate(producer_id,attempts)
                    VALUES(%s,1) ON CONFLICT(producer_id) DO UPDATE SET
                    window_start=CASE WHEN ops.producer_rate.window_start<=transaction_timestamp()-interval '1 minute'
                      THEN transaction_timestamp() ELSE ops.producer_rate.window_start END,
                    attempts=CASE WHEN ops.producer_rate.window_start<=transaction_timestamp()-interval '1 minute'
                      THEN 1 ELSE ops.producer_rate.attempts+1 END
                    RETURNING attempts''', (producer,)).fetchone()[0]
        if attempts > 120:
            raise IngestionFailure(429, 'RATE_LIMITED', retryable=True)
        with self.pool.connection() as conn:
            with conn.transaction():
                # Try-lock gives a bounded 409 for concurrent replays; unique receipt is durable.
                lock_name = f'batch:{producer}:{batch_id}'
                if not conn.execute('SELECT pg_try_advisory_xact_lock(hashtextextended(%s,0))',
                                    (lock_name,)).fetchone()[0]:
                    raise IngestionFailure(409, 'BATCH_IN_PROGRESS', retryable=True)
                old = conn.execute('''SELECT digest,state,receipt FROM ops.ingestion_receipts
                    WHERE producer_id=%s AND route_version=%s AND batch_id=%s''',
                    (producer, ROUTE, batch_id)).fetchone()
                if old:
                    if old[0] != hashed:
                        raise IngestionFailure(409, 'IDEMPOTENCY_CONFLICT')
                    if old[1] == 'ACCEPTED':
                        return old[2], True
                    if old[1] == 'REJECTED':
                        return old[2], True
                    raise IngestionFailure(409, 'BATCH_IN_PROGRESS', retryable=True)
                # Serialize overlapping logical vacancies in a global order, across batches.
                names = sorted({f"vacancy:{r['vacancy']['source_id']}:{r['vacancy']['source_vacancy_id']}"
                                if r['operation'] == 'publish' else
                                f"vacancy:{r['source_id']}:{r['source_vacancy_id']}"
                                for r in value['records']})
                for name in names:
                    if not conn.execute('SELECT pg_try_advisory_xact_lock(hashtextextended(%s,0))',
                                        (name,)).fetchone()[0]:
                        raise IngestionFailure(409, 'BATCH_IN_PROGRESS', retryable=True)
                accepted = duplicates = 0
                now = conn.execute('SELECT transaction_timestamp()').fetchone()[0]
                try:
                    with conn.transaction():
                        for index, record in enumerate(value['records']):
                            if self._record(conn, producer, record, index, now):
                                accepted += 1
                            else:
                                duplicates += 1
                        if fault == 'before_commit':
                            raise RuntimeError('synthetic crash before commit')
                except IngestionFailure as failure:
                    # Save only a sanitized rejection, never a partial catalog mutation.
                    conn.execute('''INSERT INTO ops.ingestion_receipts
                        (producer_id,route_version,batch_id,digest,state,receipt)
                        VALUES(%s,%s,%s,%s,'REJECTED',%s)''',
                        (producer, ROUTE, batch_id, hashed, Jsonb(failure.response(correlation))))
                    conn.execute("INSERT INTO ops.audit_events(action,entity_id,actor_role) VALUES('INGESTION_REJECTED',%s,'cb_ingest')",
                                 (producer,))
                    return failure.response(correlation), False
                receipt = dict(schema_version='careerbrain.ingestion-receipt.v1',
                               batch_id=batch_id, correlation_id=correlation,
                               accepted_at=timestamp(now), status='ACCEPTED',
                               accepted=accepted, duplicates=duplicates, processing='PENDING')
                conn.execute('''INSERT INTO ops.ingestion_receipts
                    (producer_id,route_version,batch_id,digest,state,receipt)
                    VALUES(%s,%s,%s,%s,'ACCEPTED',%s)''',
                    (producer, ROUTE, batch_id, hashed, Jsonb(receipt)))
                conn.execute("INSERT INTO ops.audit_events(action,entity_id,actor_role) VALUES('INGESTION_ACCEPTED',%s,'cb_ingest')",
                             (producer,))
            if fault == 'after_commit':
                raise RuntimeError('synthetic crash after commit')
        return receipt, False

    def _record(self, conn, producer: UUID, record: dict, index: int, now: datetime) -> bool:
        operation = record['operation']
        vacancy = record['vacancy'] if operation == 'publish' else record
        source, external = uid(vacancy['source_id']), vacancy['source_vacancy_id']
        event = vacancy['event'] if operation == 'publish' else record
        proof = event['provenance']
        authorization, evidence = uid(proof['authorization_id']), uid(proof['evidence_id'])
        authority = conn.execute('''SELECT a.id FROM catalog.authorizations a
            JOIN catalog.producers p ON p.id=a.producer_id
            WHERE a.id=%s AND a.source_id=%s AND a.producer_id=%s
              AND a.active AND a.usage_allowed AND p.active''',
            (authorization, source, producer)).fetchone()
        if not authority:
            raise IngestionFailure(403, 'SOURCE_NOT_AUTHORIZED', index=index, field='provenance')
        trusted = conn.execute('''SELECT digest,kind,url,observed_at,published_at,
            source_event_id,extractor_version FROM catalog.evidence
            WHERE id=%s AND source_id=%s AND authorization_id=%s''',
            (evidence, source, authorization)).fetchone()
        if not trusted or trusted[0] != proof['evidence_sha256'] or trusted[1] != proof['evidence_kind'] \
                or trusted[2] != proof['evidence_url'] or trusted[3] != instant(proof['observed_at']) \
                or trusted[5] != event['source_event_id'] or trusted[6] != proof['extractor_version']:
            raise IngestionFailure(422, 'INVALID_PUBLICATION', index=index, field='provenance')
        observed = instant(proof['observed_at'])
        if observed > now:
            raise IngestionFailure(422, 'INVALID_PUBLICATION', index=index, field='observed_at')
        existing = conn.execute('''SELECT e.id,e.vacancy_id,e.published_at,e.evidence_id,e.state,
            v.source_vacancy_id,i.record_digest FROM catalog.publication_events e
            JOIN catalog.vacancies v ON v.id=e.vacancy_id
            LEFT JOIN catalog.ingestion_events i ON i.event_id=e.id
            WHERE e.source_id=%s AND e.source_event_id=%s''',
            (source, event['source_event_id'])).fetchone()
        if operation == 'publish':
            published = instant(event['published_at'])
            if published > observed or published > now or trusted[4] != published:
                raise IngestionFailure(422, 'INVALID_PUBLICATION', index=index, field='published_at')
            self._contact(conn, authorization, vacancy['access'], index)
            record_hash = digest(record)
            if existing:
                if existing[5] == external and existing[6] == record_hash:
                    return False
                raise IngestionFailure(409, 'EVENT_CONFLICT', index=index, field='source_event_id')
            prior = None
            if event['kind'] == 'republication':
                prior = conn.execute('''SELECT e.id,e.vacancy_id,e.published_at,e.evidence_id
                    FROM catalog.publication_events e JOIN catalog.vacancies v ON v.id=e.vacancy_id
                    WHERE e.source_id=%s AND e.source_event_id=%s AND v.source_vacancy_id=%s''',
                    (source, event['previous_source_event_id'], external)).fetchone()
                if not prior or prior[2] >= published or prior[3] == evidence:
                    raise IngestionFailure(422, 'INVALID_PUBLICATION', index=index, field='previous_source_event_id')
            row = conn.execute('''SELECT id,content,content_version FROM catalog.vacancies
                WHERE source_id=%s AND source_vacancy_id=%s''', (source, external)).fetchone()
            content = {key: vacancy[key] for key in ('title','organization','description','requirements',
                                                      'modality','location','employment_type','access')}
            if row is None:
                if event['kind'] != 'original':
                    raise IngestionFailure(409, 'EVENT_CONFLICT', index=index)
                vacancy_id = conn.execute('''INSERT INTO catalog.vacancies(source_id,source_vacancy_id,content)
                    VALUES(%s,%s,%s) RETURNING id''', (source, external, Jsonb(content))).fetchone()[0]
            else:
                vacancy_id = row[0]
                if event['kind'] == 'original' or (prior and prior[1] != vacancy_id):
                    raise IngestionFailure(409, 'EVENT_CONFLICT', index=index)
                conn.execute('''UPDATE catalog.vacancies SET content=%s,content_version=content_version+1
                    WHERE id=%s''', (Jsonb(content), vacancy_id))
            event_id = conn.execute('''INSERT INTO catalog.publication_events
                (vacancy_id,source_id,source_event_id,kind,predecessor_id,published_at,observed_at,evidence_id)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',
                (vacancy_id, source, event['source_event_id'], event['kind'], prior[0] if prior else None,
                 published, observed, evidence)).fetchone()[0]
            conn.execute('INSERT INTO catalog.ingestion_events VALUES(%s,%s)', (event_id, record_hash))
            self._outbox(conn, event_id, 'publish', 'PUBLISHED', job=True)
            return True
        if not existing or existing[5] != external:
            raise IngestionFailure(409, 'EVENT_CONFLICT', index=index, field='source_event_id')
        revision = record['source_revision']
        record_hash = digest(record)
        old = conn.execute('SELECT event_id,digest FROM catalog.revisions WHERE source_id=%s AND revision_id=%s',
                           (source, revision)).fetchone()
        if old:
            if old == (existing[0], record_hash):
                return False
            raise IngestionFailure(409, 'EVENT_CONFLICT', index=index, field='source_revision')
        if existing[4] != 'ACTIVE':
            raise IngestionFailure(409, 'EVENT_CONFLICT', index=index, field='source_event_id')
        if operation == 'correct':
            patch = record['correction']
            if 'access' in patch:
                self._contact(conn, authorization, patch['access'], index)
            row = conn.execute('SELECT content FROM catalog.vacancies WHERE id=%s', (existing[1],)).fetchone()
            content = dict(row[0]); content.update(patch)
            conn.execute('''UPDATE catalog.vacancies SET content=%s,content_version=content_version+1
                WHERE id=%s''', (Jsonb(content), existing[1]))
            self._outbox(conn, existing[0], revision, 'CORRECTED', job=True)
        else:
            state = 'CLOSED' if operation == 'close' else 'WITHDRAWN'
            conn.execute('UPDATE catalog.publication_events SET state=%s WHERE id=%s', (state, existing[0]))
            self._outbox(conn, existing[0], revision, 'REMOVED')
        conn.execute('INSERT INTO catalog.revisions VALUES(%s,%s,%s,%s)',
                     (source, revision, existing[0], record_hash))
        return True

    @staticmethod
    def _contact(conn, authorization, contact: dict, index: int):
        if not conn.execute('''SELECT 1 FROM catalog.official_contacts
            WHERE authorization_id=%s AND kind=%s AND value=%s''',
            (authorization, contact['kind'], contact['value'])).fetchone():
            raise IngestionFailure(422, 'INVALID_CONTACT', index=index, field='access')

    @staticmethod
    def _outbox(conn, event_id, version: str, kind: str, *, job: bool = False):
        conn.execute('''INSERT INTO queue.catalog_outbox(event_id,event_version,kind)
            VALUES(%s,%s,%s)''', (event_id, version, kind))
        if job:
            conn.execute('''INSERT INTO queue.catalog_jobs(event_id,task_version)
                VALUES(%s,%s)''', (event_id, version))

    def status(self, producer: UUID, batch_id: str) -> dict | None:
        with self.pool.connection() as conn:
            row = conn.execute('''SELECT state,receipt FROM ops.ingestion_receipts
                WHERE producer_id=%s AND route_version=%s AND batch_id=%s''',
                (producer, ROUTE, batch_id)).fetchone()
        if not row or row[0] != 'ACCEPTED':
            return None
        total = row[1]['accepted']
        return dict(schema_version='careerbrain.batch-status.v1', batch_id=batch_id,
                    status='PENDING', total=total, completed=0, failed=0)
