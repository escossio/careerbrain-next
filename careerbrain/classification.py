"""Global classification over versioned vacancy content; no provider traffic."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import re
import time
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from tools.contracts import ContractError, digest, validate


class TransientFailure(Exception):
    pass


class ProviderGate(Exception):
    """Quota or credential gate; caller stops new work until external action."""


@dataclass(frozen=True)
class ClassificationConfig:
    taxonomy_version: str
    model_version: str
    prompt_version: str
    timeout_seconds: int = 10
    lease_seconds: int = 30
    max_attempts: int = 3

    def __post_init__(self):
        for value in (self.taxonomy_version, self.model_version, self.prompt_version):
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}', value):
                raise ValueError('Invalid classifier version')
        if not 1 <= self.timeout_seconds < self.lease_seconds <= 300 or self.max_attempts != 3:
            raise ValueError('Invalid bounded timeout or attempt policy')


@dataclass(frozen=True)
class Claim:
    job_id: UUID
    event_id: UUID
    vacancy_id: UUID
    content: dict
    content_version: int
    content_digest: str
    attempts: int
    owner: UUID
    fencing: int


class DeterministicClassifier:
    """Synthetic rules for integration, not a quality model or fallback provider."""

    PATTERNS = (
        ('description', 'enfermagem', 'skill'),
        ('description', 'instalações elétricas', 'activity'),
        ('description', 'atendimento ao cliente', 'activity'),
        ('description', 'Python', 'skill'),
    )

    def classify(self, content: dict, envelope: dict, *, timeout_seconds: int) -> dict:
        attributes = []
        for field, pattern, name in self.PATTERNS:
            match = re.search(re.escape(pattern), content.get(field, ''), re.IGNORECASE)
            if match:
                attributes.append(dict(name=name, value=match.group(0), basis='explicit',
                                       confidence=1, evidence=[dict(field=field, quote=match.group(0),
                                                                   start=match.start(), end=match.end())]))
        status = 'READY' if attributes else 'UNCERTAIN'
        if not attributes:
            attributes = [dict(name='activity', value='unknown', basis='unknown',
                               confidence=0, evidence=[])]
        return dict(schema_version='careerbrain.semantics.v1', status=status,
                    attributes=attributes, **envelope)


def validate_result(content: dict, result: dict, envelope: dict) -> None:
    validate('vacancy-semantics', result)
    try:
        json.dumps(result, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, OverflowError) as error:
        raise ContractError('SCHEMA_INVALID') from error
    if any(result[key] != value for key, value in envelope.items()):
        raise ContractError('SCHEMA_INVALID')
    supported = 0
    for attribute in result['attributes']:
        basis, proofs = attribute['basis'], attribute['evidence']
        if basis == 'unknown':
            if proofs or attribute['confidence'] != 0:
                raise ContractError('INSUFFICIENT_CONTENT')
            continue
        if not proofs:
            raise ContractError('INSUFFICIENT_CONTENT')
        for proof in proofs:
            field = proof['field']
            if field.startswith('requirements/'):
                index = field.removeprefix('requirements/')
                if not index.isdecimal() or int(index) >= len(content['requirements']):
                    raise ContractError('INSUFFICIENT_CONTENT')
                source = content['requirements'][int(index)]
            elif field in ('title', 'organization', 'description', 'location'):
                source = content[field]
            else:
                raise ContractError('INSUFFICIENT_CONTENT')
            if proof['end'] <= proof['start'] or source[proof['start']:proof['end']] != proof['quote']:
                raise ContractError('INSUFFICIENT_CONTENT')
        supported += 1
    if result['status'] == 'READY' and not supported:
        raise ContractError('INSUFFICIENT_CONTENT')
    if result['status'] == 'UNCERTAIN' and any(a['basis'] == 'inferred' for a in result['attributes']):
        raise ContractError('INSUFFICIENT_CONTENT')


class GlobalClassifier:
    def __init__(self, pool, config: ClassificationConfig, adapter):
        self.pool, self.config, self.adapter = pool, config, adapter
        with pool.connection() as conn:
            if conn.execute('SELECT current_user').fetchone()[0] != 'cb_global_worker':
                raise ValueError('Runtime database role mismatch')
            conn.execute('''INSERT INTO ops.classifier_policy
                (taxonomy_version,model_version,prompt_version) VALUES(%s,%s,%s)
                ON CONFLICT(singleton) DO NOTHING''',
                (config.taxonomy_version,config.model_version,config.prompt_version))

    def _policy_current(self, conn) -> bool:
        row = conn.execute('''SELECT taxonomy_version,model_version,prompt_version
            FROM ops.classifier_policy WHERE singleton FOR SHARE''').fetchone()
        return row == (self.config.taxonomy_version,self.config.model_version,
                       self.config.prompt_version)

    def _gate_open(self, conn) -> bool:
        row = conn.execute('SELECT state FROM ops.classifier_gate WHERE model_version=%s',
                           (self.config.model_version,)).fetchone()
        return row is None or row[0] == 'OPEN'

    def claim(self) -> Claim | None:
        owner = uuid4()
        with self.pool.connection() as conn, conn.transaction():
            if not self._gate_open(conn) or not self._policy_current(conn):
                return None
            # Exhausted or obsolete work cannot occupy the ready queue forever.
            conn.execute('''UPDATE queue.catalog_jobs j SET state='FAILED',lease_owner=NULL,
                lease_until=NULL,last_error_code='RETRY_EXHAUSTED'
                WHERE (j.state='READY' OR j.state='LEASED' AND j.lease_until<=transaction_timestamp())
                  AND j.attempts>=3''')
            conn.execute('''UPDATE queue.catalog_jobs j SET state='DONE',lease_owner=NULL,
                lease_until=NULL,last_error_code='STALE'
                FROM catalog.publication_events e JOIN catalog.vacancies v ON v.id=e.vacancy_id
                WHERE j.event_id=e.id
                  AND (j.state='READY' OR j.state='LEASED' AND j.lease_until<=transaction_timestamp())
                  AND (e.state<>'ACTIVE' OR j.content_version IS NOT NULL
                       AND j.content_version<>v.content_version)''')
            row = conn.execute('''SELECT j.id,j.event_id,j.attempts,j.fencing_token,
                    j.content_version,j.content_digest,v.id,v.content,v.content_version
                FROM queue.catalog_jobs j JOIN catalog.publication_events e ON e.id=j.event_id
                JOIN catalog.vacancies v ON v.id=e.vacancy_id
                WHERE (j.state='READY' AND j.available_at<=transaction_timestamp()
                       OR j.state='LEASED' AND j.lease_until<=transaction_timestamp())
                  AND j.attempts<3 AND e.state='ACTIVE'
                  AND (j.taxonomy_version IS NULL OR j.taxonomy_version=%s)
                  AND (j.model_version IS NULL OR j.model_version=%s)
                  AND (j.prompt_version IS NULL OR j.prompt_version=%s)
                ORDER BY CASE WHEN j.created_at<=transaction_timestamp()-interval '30 minutes' THEN 0 ELSE 1 END,
                  CASE WHEN j.created_at<=transaction_timestamp()-interval '30 minutes' THEN j.created_at END ASC NULLS LAST,
                  CASE WHEN j.created_at>transaction_timestamp()-interval '30 minutes' THEN e.published_at END DESC NULLS LAST,
                  j.id
                FOR UPDATE OF j SKIP LOCKED LIMIT 1''',
                (self.config.taxonomy_version,self.config.model_version,self.config.prompt_version)).fetchone()
            if row is None:
                return None
            job_id,event_id,attempts,fencing,old_version,old_digest,vacancy_id,content,version = row
            content_hash = digest(content)
            if old_version is not None and (old_version != version or old_digest != content_hash):
                conn.execute("UPDATE queue.catalog_jobs SET state='DONE',last_error_code='STALE' WHERE id=%s",
                             (job_id,))
                return None
            lease = conn.execute('''UPDATE queue.catalog_jobs SET state='LEASED',attempts=attempts+1,
                    fencing_token=fencing_token+1,lease_owner=%s,
                    lease_until=transaction_timestamp()+(%s * interval '1 second'),
                    content_version=%s,content_digest=%s,taxonomy_version=%s,
                    model_version=%s,prompt_version=%s,last_error_code=NULL WHERE id=%s
                    RETURNING attempts,fencing_token''',
                (owner,self.config.lease_seconds,version,content_hash,self.config.taxonomy_version,
                 self.config.model_version,self.config.prompt_version,job_id)).fetchone()
            return Claim(job_id,event_id,vacancy_id,content,version,content_hash,lease[0],owner,lease[1])

    def _leased(self, conn, claim: Claim):
        row = conn.execute('''SELECT j.state,j.lease_until,e.state,v.content_version
            FROM queue.catalog_jobs j JOIN catalog.publication_events e ON e.id=j.event_id
            JOIN catalog.vacancies v ON v.id=e.vacancy_id
            WHERE j.id=%s AND j.lease_owner=%s AND j.fencing_token=%s FOR UPDATE OF j''',
            (claim.job_id,claim.owner,claim.fencing)).fetchone()
        if not row or row[0] != 'LEASED' or row[1] <= conn.execute('SELECT clock_timestamp()').fetchone()[0]:
            return None
        return row

    def renew(self, claim: Claim) -> bool:
        with self.pool.connection() as conn, conn.transaction():
            if not self._leased(conn, claim):
                return False
            conn.execute('''UPDATE queue.catalog_jobs SET
                lease_until=transaction_timestamp()+(%s * interval '1 second') WHERE id=%s''',
                (self.config.lease_seconds,claim.job_id))
            return True

    def _defer(self, claim: Claim):
        with self.pool.connection() as conn, conn.transaction():
            if self._leased(conn, claim):
                conn.execute('''UPDATE queue.catalog_jobs SET state='READY',attempts=attempts-1,
                    lease_owner=NULL,lease_until=NULL,available_at=transaction_timestamp()+interval '2 seconds'
                    WHERE id=%s''', (claim.job_id,))

    def _failure(self, claim: Claim, code: str, *, block: bool = False) -> str:
        with self.pool.connection() as conn, conn.transaction():
            if not self._leased(conn, claim):
                return 'FENCED'
            if block:
                conn.execute('''INSERT INTO ops.classifier_gate(model_version,state,reason)
                    VALUES(%s,'BLOCKED',%s) ON CONFLICT(model_version) DO UPDATE
                    SET state='BLOCKED',reason=EXCLUDED.reason,updated_at=transaction_timestamp()''',
                    (self.config.model_version,code))
            exhausted = claim.attempts >= self.config.max_attempts and not block
            conn.execute('''UPDATE queue.catalog_jobs SET state=%s,lease_owner=NULL,lease_until=NULL,
                available_at=transaction_timestamp()+(%s * interval '1 second'),
                last_error_code=%s,attempts=attempts-%s WHERE id=%s''',
                ('FAILED' if exhausted else 'READY',
                 min(300,2**claim.attempts + claim.job_id.int % 3) if not block else 60,
                 code,1 if block else 0,claim.job_id))
            return 'BLOCKED' if block else 'FAILED' if exhausted else 'RETRY'

    def _complete(self, claim: Claim, result: dict | None) -> str:
        with self.pool.connection() as conn, conn.transaction():
            row = self._leased(conn, claim)
            if row is None:
                return 'FENCED'
            current_version = conn.execute('''SELECT content_version FROM catalog.vacancies
                WHERE id=%s FOR SHARE''', (claim.vacancy_id,)).fetchone()[0]
            state = conn.execute('''SELECT state FROM catalog.publication_events
                WHERE id=%s FOR SHARE''', (claim.event_id,)).fetchone()[0]
            if state != 'ACTIVE' or current_version != claim.content_version or not self._policy_current(conn):
                conn.execute("UPDATE queue.catalog_jobs SET state='DONE',lease_owner=NULL,lease_until=NULL,last_error_code='STALE' WHERE id=%s",
                             (claim.job_id,))
                return 'STALE'
            key = (claim.vacancy_id,claim.content_version,claim.content_digest,
                   self.config.taxonomy_version,self.config.model_version,self.config.prompt_version)
            cache = conn.execute('''SELECT id,status FROM catalog.classification_cache
                WHERE vacancy_id=%s AND content_version=%s AND content_digest=%s
                  AND taxonomy_version=%s AND model_version=%s AND prompt_version=%s''',key).fetchone()
            if cache is None:
                if result is None:
                    raise RuntimeError('Validated classifier result is required')
                cache = conn.execute('''INSERT INTO catalog.classification_cache
                    (vacancy_id,content_version,content_digest,taxonomy_version,model_version,
                     prompt_version,status,result) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
                    RETURNING id,status''', (*key,result['status'],Jsonb(result))).fetchone()
            events = conn.execute('''SELECT id FROM catalog.publication_events
                WHERE vacancy_id=%s AND state='ACTIVE' ORDER BY id FOR SHARE''',
                (claim.vacancy_id,)).fetchall()
            for (event_id,) in events:
                conn.execute('''INSERT INTO catalog.event_classifications(event_id,cache_id)
                    VALUES(%s,%s) ON CONFLICT(event_id) DO UPDATE SET cache_id=EXCLUDED.cache_id,
                    updated_at=transaction_timestamp() WHERE catalog.event_classifications.cache_id<>EXCLUDED.cache_id''',
                    (event_id,cache[0]))
                conn.execute('''INSERT INTO queue.classification_outbox(event_id,cache_id,kind)
                    VALUES(%s,%s,%s) ON CONFLICT(event_id,cache_id) DO NOTHING''',
                    (event_id,cache[0],cache[1]))
            conn.execute("UPDATE queue.catalog_jobs SET state='DONE',lease_owner=NULL,lease_until=NULL WHERE id=%s",
                         (claim.job_id,))
            return cache[1]

    def enqueue_reclassify(self, event_id: UUID) -> bool:
        """Explicit version refresh; does not replace producer publication events."""
        with self.pool.connection() as conn, conn.transaction():
            if not self._policy_current(conn):
                return False
            row = conn.execute('''SELECT v.content_version,v.content
                FROM catalog.publication_events e JOIN catalog.vacancies v ON v.id=e.vacancy_id
                WHERE e.id=%s AND e.state='ACTIVE' ''', (event_id,)).fetchone()
            if row is None:
                return False
            version,content = row
            task = ':'.join(('classify',str(version),self.config.taxonomy_version,
                             self.config.model_version,self.config.prompt_version))
            return conn.execute('''INSERT INTO queue.catalog_jobs
                (event_id,task_version,content_version,content_digest,taxonomy_version,
                 model_version,prompt_version) VALUES(%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(event_id,task_version) DO NOTHING RETURNING id''',
                (event_id,task,version,digest(content),self.config.taxonomy_version,
                 self.config.model_version,self.config.prompt_version)).fetchone() is not None

    def run_once(self) -> str | None:
        claim = self.claim()
        if claim is None:
            return None
        key = ':'.join((str(claim.vacancy_id),str(claim.content_version),claim.content_digest,
                        self.config.taxonomy_version,self.config.model_version,self.config.prompt_version))
        with self.pool.connection() as lock_conn:
            locked = lock_conn.execute('SELECT pg_try_advisory_lock(hashtextextended(%s,0))',
                                       (key,)).fetchone()[0]
            if not locked:
                self._defer(claim)
                return 'DEFERRED'
            try:
                with self.pool.connection() as conn:
                    cached = conn.execute('''SELECT 1 FROM catalog.classification_cache
                        WHERE vacancy_id=%s AND content_version=%s AND content_digest=%s
                          AND taxonomy_version=%s AND model_version=%s AND prompt_version=%s''',
                        (claim.vacancy_id,claim.content_version,claim.content_digest,
                         self.config.taxonomy_version,self.config.model_version,
                         self.config.prompt_version)).fetchone()
                if cached:
                    return self._complete(claim, None)
                envelope = dict(vacancy_id=str(claim.vacancy_id),
                                content_version=f'content-v{claim.content_version}',
                                taxonomy_version=self.config.taxonomy_version,
                                model_version=self.config.model_version,
                                prompt_version=self.config.prompt_version)
                started = time.monotonic()
                try:
                    result = self.adapter.classify(claim.content,envelope,
                                                   timeout_seconds=self.config.timeout_seconds)
                    if time.monotonic()-started > self.config.timeout_seconds:
                        raise TimeoutError()
                    validate_result(claim.content,result,envelope)
                except ProviderGate:
                    return self._failure(claim,'PROVIDER_GATE',block=True)
                except (TimeoutError,TransientFailure):
                    return self._failure(claim,'TRANSIENT')
                except (ContractError,ValueError,TypeError,KeyError):
                    return self._failure(claim,'INVALID_RESULT')
                except Exception:
                    return self._failure(claim,'ADAPTER_ERROR')
                return self._complete(claim,result)
            finally:
                lock_conn.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))', (key,))
