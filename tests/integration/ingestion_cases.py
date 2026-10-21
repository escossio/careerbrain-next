"""Producer ingestion proofs; runs only in a disposable PostgreSQL worker."""
import concurrent.futures
from copy import deepcopy
from datetime import timedelta
import hashlib
import io
import json
import os
import unittest
from uuid import uuid4

import psycopg
from psycopg.conninfo import make_conninfo

from careerbrain.api import CareerBrainAPI
from careerbrain.db import migrate, tenant_pool
from careerbrain.ingestion import IngestionFailure, IngestionService

DB = os.environ['NEXT_TEST_DATABASE']
SOCKET = os.environ['NEXT_TEST_SOCKET']
assert DB.startswith('cbn_test_') and os.environ.get('NEXT_DISPOSABLE_CI') == '1'


def connect(role='postgres'):
    return psycopg.connect(dbname=DB, user=role, host=SOCKET, autocommit=True)


class IngestionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with connect('cb_migrator') as conn:
            migrate(conn, target=5)
            migrate(conn, target=5)
        cls.pool = tenant_pool(make_conninfo(dbname=DB, user='cb_ingest', host=SOCKET), max_size=4)
        cls.pool.wait(timeout=5)
        cls.service = IngestionService(cls.pool)

    @classmethod
    def tearDownClass(cls):
        cls.pool.close()

    def setUp(self):
        self.admin = connect()
        self.addCleanup(self.admin.close)
        self.producer, self.source, self.authorization = uuid4(), uuid4(), uuid4()
        self.evidence = uuid4()
        self.token = 'synthetic-' + uuid4().hex + uuid4().hex
        self.access = 'https://example.org/jobs/synthetic'
        self.published = self.admin.execute("SELECT transaction_timestamp()-interval '2 hours'").fetchone()[0]
        self.observed = self.published + timedelta(hours=1)
        self.admin.execute('INSERT INTO catalog.producers(id) VALUES(%s)', (self.producer,))
        self.admin.execute('INSERT INTO catalog.sources VALUES(%s,%s)', (self.source, 'synthetic source'))
        self.admin.execute('''INSERT INTO catalog.authorizations(id,producer_id,source_id,active,usage_allowed)
            VALUES(%s,%s,%s,true,true)''', (self.authorization, self.producer, self.source))
        self.admin.execute('INSERT INTO catalog.official_contacts VALUES(%s,%s,%s)',
                           (self.authorization, 'https', self.access))
        self.admin.execute("INSERT INTO catalog.producer_tokens VALUES(%s,%s,'ingestion:write',true)",
                           (hashlib.sha256(self.token.encode()).hexdigest(), self.producer))
        self.add_evidence(self.evidence, 'event-one', self.published)

    def add_evidence(self, evidence, event, published):
        self.admin.execute('''INSERT INTO catalog.evidence(id,source_id,authorization_id,digest,
            kind,url,observed_at,published_at,source_event_id,extractor_version)
            VALUES(%s,%s,%s,%s,'source_api',%s,%s,%s,%s,'synthetic-v1')''',
            (evidence, self.source, self.authorization, 'a'*64, self.access,
             published + timedelta(hours=1), published, event))
        self.admin.execute('INSERT INTO catalog.evidence_approvals VALUES(%s,%s,%s)',
                           (evidence, self.source, self.authorization))

    def batch(self, *, batch_id=None, event='event-one', evidence=None, published=None, kind='original', previous=None):
        published = published or self.published
        proof = dict(authorization_id=str(self.authorization), evidence_id=str(evidence or self.evidence),
                     evidence_sha256='a'*64, evidence_kind='source_api', evidence_url=self.access,
                     observed_at=(published + timedelta(hours=1)).isoformat(), extractor_version='synthetic-v1')
        publication = dict(source_event_id=event, kind=kind,
                           published_at=published.isoformat(), provenance=proof)
        if previous:
            publication['previous_source_event_id'] = previous
        vacancy = dict(source_id=str(self.source), source_vacancy_id='logical-one',
                       title='Maintenance Engineer', organization='Synthetic Company',
                       description='Inspect and maintain electrical installations, write clear reports, and verify safe operation in the synthetic example.',
                       requirements=['Electrical systems'], modality='onsite', location='Example City',
                       employment_type='employee', access=dict(kind='https', value=self.access),
                       event=publication)
        return dict(schema_version='careerbrain.ingestion.v1', batch_id=batch_id or 'batch-'+uuid4().hex,
                    records=[dict(operation='publish', vacancy=vacancy)])

    def submit(self, batch, *, token=None, fault=None):
        value = self.service.decode(json.dumps(batch).encode(), batch['batch_id'])
        producer = self.service.authenticate(token or self.token)
        return self.service.submit(producer, value, fault=fault)

    def counts(self):
        return tuple(self.admin.execute(f'SELECT count(*) FROM {table} WHERE '+condition, args).fetchone()[0]
                     for table, condition, args in [
                         ('catalog.publication_events', 'source_id=%s', (self.source,)),
                         ('queue.catalog_outbox', 'event_id IN (SELECT id FROM catalog.publication_events WHERE source_id=%s)', (self.source,)),
                         ('queue.catalog_jobs', 'event_id IN (SELECT id FROM catalog.publication_events WHERE source_id=%s)', (self.source,))])

    def test_authenticated_atomic_publish_receipt_replay_status_and_eligibility_time(self):
        batch = self.batch()
        receipt, replay = self.submit(batch)
        self.assertFalse(replay)
        self.assertEqual((receipt['accepted'], receipt['duplicates'], self.counts()), (1, 0, (1, 1, 1)))
        self.assertEqual(self.submit(batch), (receipt, True))
        self.assertEqual(self.service.status(self.producer, batch['batch_id'])['total'], 1)
        self.assertEqual(self.admin.execute('SELECT published_at FROM catalog.publication_events WHERE source_id=%s',
                                            (self.source,)).fetchone()[0], self.published)
        other = deepcopy(batch); other['records'][0]['vacancy']['title'] = 'Other'
        with self.assertRaises(IngestionFailure) as error:
            self.submit(other)
        self.assertEqual(error.exception.code, 'IDEMPOTENCY_CONFLICT')
        self.assertEqual(self.counts(), (1, 1, 1))
        self.assertEqual(self.admin.execute("SELECT count(*) FROM ops.audit_events WHERE entity_id=%s AND action='INGESTION_ACCEPTED'",
                                            (self.producer,)).fetchone()[0], 1)

    def test_duplicate_event_is_not_new_and_changed_publish_conflicts(self):
        batch = self.batch(); self.submit(batch)
        again = deepcopy(batch); again['batch_id'] = 'another-'+uuid4().hex
        receipt, _ = self.submit(again)
        self.assertEqual((receipt['accepted'], receipt['duplicates'], self.counts()), (0, 1, (1, 1, 1)))
        changed = deepcopy(again); changed['batch_id'] = 'changed-'+uuid4().hex
        changed['records'][0]['vacancy']['description'] += ' Changed.'
        error, _ = self.submit(changed)
        self.assertEqual(error['code'], 'EVENT_CONFLICT')
        self.assertEqual(self.counts(), (1, 1, 1))

    def test_same_proof_from_second_authorized_producer_maps_to_existing_event(self):
        self.submit(self.batch())
        second_producer, second_auth = uuid4(), uuid4()
        second_token = 'synthetic-' + uuid4().hex + uuid4().hex
        self.admin.execute('INSERT INTO catalog.producers(id) VALUES(%s)', (second_producer,))
        self.admin.execute('''INSERT INTO catalog.authorizations(id,producer_id,source_id,active,usage_allowed)
            VALUES(%s,%s,%s,true,true)''', (second_auth, second_producer, self.source))
        self.admin.execute('INSERT INTO catalog.official_contacts VALUES(%s,%s,%s)',
                           (second_auth, 'https', self.access))
        self.admin.execute('INSERT INTO catalog.evidence_approvals VALUES(%s,%s,%s)',
                           (self.evidence, self.source, second_auth))
        self.admin.execute("INSERT INTO catalog.producer_tokens VALUES(%s,%s,'ingestion:write',true)",
                           (hashlib.sha256(second_token.encode()).hexdigest(), second_producer))
        batch = self.batch(); batch['records'][0]['vacancy']['event']['provenance']['authorization_id'] = str(second_auth)
        value = self.service.decode(json.dumps(batch).encode(), batch['batch_id'])
        producer = self.service.authenticate(second_token)
        receipt, _ = self.service.submit(producer, value)
        self.assertEqual((receipt['accepted'], receipt['duplicates'], self.counts()), (0, 1, (1, 1, 1)))
        self.admin.execute('UPDATE catalog.authorizations SET active=false WHERE id=%s', (second_auth,))
        next_batch = self.batch(); next_batch['records'][0]['vacancy']['event']['provenance']['authorization_id'] = str(second_auth)
        denied, _ = self.service.submit(producer, self.service.decode(json.dumps(next_batch).encode(), next_batch['batch_id']))
        self.assertEqual(denied['code'], 'SOURCE_NOT_AUTHORIZED')

    def test_invalid_second_record_rolls_back_entire_batch_and_records_rejection(self):
        batch = self.batch(); second = deepcopy(batch['records'][0]); second['vacancy']['event']['source_event_id'] = 'other-event'
        second['vacancy']['access']['value'] = 'https://example.org/jobs/unapproved'
        batch['records'].append(second)
        error, _ = self.submit(batch)
        self.assertEqual(error['code'], 'INVALID_PUBLICATION')
        self.assertEqual(self.counts(), (0, 0, 0))
        state = self.admin.execute('SELECT state FROM ops.ingestion_receipts WHERE producer_id=%s AND batch_id=%s',
                                   (self.producer, batch['batch_id'])).fetchone()[0]
        self.assertEqual(state, 'REJECTED')
        self.assertEqual(self.admin.execute("SELECT count(*) FROM ops.audit_events WHERE entity_id=%s AND action='INGESTION_REJECTED'",
                                            (self.producer,)).fetchone()[0], 1)

    def test_rate_limit_is_per_producer_and_has_no_partial_commit(self):
        self.admin.execute('INSERT INTO ops.producer_rate(producer_id,attempts) VALUES(%s,120)',
                           (self.producer,))
        with self.assertRaises(IngestionFailure) as error:
            self.submit(self.batch())
        self.assertEqual((error.exception.status, error.exception.code), (429, 'RATE_LIMITED'))
        self.assertEqual(self.counts(), (0, 0, 0))

    def test_structural_rejection_keeps_digest_and_requires_new_key(self):
        batch = self.batch()
        del batch['records'][0]['vacancy']['title']
        error, replay = self.submit(batch)
        self.assertEqual((error['code'], replay), ('SCHEMA_INVALID', False))
        self.assertEqual(error['items'][0]['index'], 0)
        self.assertEqual(self.submit(batch), (error, True))
        repaired = self.batch(batch_id=batch['batch_id'])
        with self.assertRaises(IngestionFailure) as conflict:
            self.submit(repaired)
        self.assertEqual(conflict.exception.code, 'IDEMPOTENCY_CONFLICT')
        self.assertEqual(self.counts(), (0, 0, 0))

    def test_auth_scope_source_and_sql_permissions(self):
        with self.assertRaises(IngestionFailure):
            self.service.authenticate('wrong-' + uuid4().hex)
        batch = self.batch(); batch['records'][0]['vacancy']['source_id'] = str(uuid4())
        error, _ = self.submit(batch)
        self.assertEqual(error['code'], 'SOURCE_NOT_AUTHORIZED')
        with connect('cb_ingest') as conn:
            for sql in ('SELECT * FROM catalog.producer_tokens', 'SELECT * FROM identity.accounts',
                        'INSERT INTO catalog.authorizations VALUES(gen_random_uuid(),gen_random_uuid(),gen_random_uuid(),true)'):
                with self.subTest(sql=sql), self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    conn.execute(sql)

    def test_temporal_and_contact_and_proof_are_fail_closed(self):
        for change in ('future', 'contact', 'proof'):
            with self.subTest(change=change):
                batch = self.batch()
                vacancy = batch['records'][0]['vacancy']
                if change == 'future':
                    vacancy['event']['published_at'] = (self.published + timedelta(days=1)).isoformat()
                elif change == 'contact':
                    vacancy['access']['value'] = 'https://example.org/jobs/other'
                else:
                    vacancy['event']['provenance']['evidence_sha256'] = 'b'*64
                error, _ = self.submit(batch)
                self.assertIn(error['code'], ('INVALID_PUBLICATION', 'INVALID_CONTACT'))
                self.assertEqual(self.counts(), (0, 0, 0))

    def test_correction_republication_close_and_no_reopening(self):
        self.submit(self.batch())
        proof = self.batch()['records'][0]['vacancy']['event']['provenance']
        correction = dict(operation='correct', source_id=str(self.source), source_vacancy_id='logical-one',
                          source_event_id='event-one', source_revision='revision-one', provenance=proof,
                          correction=dict(title='Updated Synthetic Title'))
        changed = dict(schema_version='careerbrain.ingestion.v1', batch_id='correct-'+uuid4().hex,
                       records=[correction])
        self.assertEqual(self.submit(changed)[0]['accepted'], 1)
        changed['batch_id'] = 'correct-replay-'+uuid4().hex
        self.assertEqual(self.submit(changed)[0]['duplicates'], 1)
        next_time = self.published + timedelta(minutes=30)
        second_evidence = uuid4(); self.add_evidence(second_evidence, 'event-two', next_time)
        repub = self.batch(event='event-two', evidence=second_evidence, published=next_time,
                           kind='republication', previous='event-one')
        self.assertEqual(self.submit(repub)[0]['accepted'], 1)
        closing = dict(schema_version='careerbrain.ingestion.v1', batch_id='close-'+uuid4().hex,
                       records=[dict(operation='close', source_id=str(self.source),
                                     source_vacancy_id='logical-one', source_event_id='event-two',
                                     source_revision='revision-two',
                                     provenance=repub['records'][0]['vacancy']['event']['provenance'])])
        self.assertEqual(self.submit(closing)[0]['accepted'], 1)
        self.assertEqual(self.counts(), (2, 4, 3))
        reopen = deepcopy(repub); reopen['batch_id'] = 'reopen-'+uuid4().hex
        self.assertEqual(self.submit(reopen)[0]['duplicates'], 1)
        self.assertEqual(self.admin.execute("SELECT state FROM catalog.publication_events WHERE source_event_id='event-two' AND source_id=%s",
                                            (self.source,)).fetchone()[0], 'CLOSED')

    def test_crash_before_and_after_commit(self):
        batch = self.batch()
        with self.assertRaises(RuntimeError):
            self.submit(batch, fault='before_commit')
        self.assertEqual(self.counts(), (0, 0, 0))
        with self.assertRaises(RuntimeError):
            self.submit(batch, fault='after_commit')
        self.assertEqual(self.counts(), (1, 1, 1))
        self.assertEqual(self.submit(batch)[0]['accepted'], 1)

    def test_concurrent_same_key_returns_retry_then_stable_replay(self):
        batch = self.batch(); value = self.service.decode(json.dumps(batch).encode(), batch['batch_id'])
        lock_name = f'batch:{self.producer}:{batch["batch_id"]}'
        with connect('cb_ingest') as blocker:
            with blocker.transaction():
                blocker.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (lock_name,))
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                    results = list(executor.map(lambda _: self._blocked_submit(value), range(2)))
                self.assertEqual(results, ['BATCH_IN_PROGRESS', 'BATCH_IN_PROGRESS'])
        receipt, _ = self.service.submit(self.producer, value)
        self.assertEqual(self.service.submit(self.producer, value), (receipt, True))

    def _blocked_submit(self, value):
        try:
            self.service.submit(self.producer, value)
        except IngestionFailure as error:
            return error.code
        return 'unexpected success'

    def test_wsgi_rejects_user_bearer_and_reports_replay_header(self):
        api = CareerBrainAPI(None, self.service)
        batch = self.batch(); raw = json.dumps(batch).encode()
        def request(token):
            env = dict(REQUEST_METHOD='POST', PATH_INFO='/v1/ingestion/batches',
                       HTTP_AUTHORIZATION='Bearer '+token, HTTP_IDEMPOTENCY_KEY=batch['batch_id'],
                       CONTENT_TYPE='application/json', CONTENT_LENGTH=str(len(raw)),
                       **{'wsgi.input': io.BytesIO(raw)})
            metadata = []
            body = b''.join(api(env, lambda status, headers: metadata.append((status, headers))))
            return metadata[0], json.loads(body)
        self.assertEqual(request('synthetic-user-session-token')[0][0], '401 Unauthorized')
        self.assertEqual(request(self.token)[0][0], '202 Accepted')
        self.assertIn(('Idempotent-Replay', 'true'), request(self.token)[0][1])
        self.assertEqual(self.counts(), (1, 1, 1))


if __name__ == '__main__':
    unittest.main(verbosity=2)
