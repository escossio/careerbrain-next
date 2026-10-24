"""Resume privacy tests. Run only in the networkless disposable PostgreSQL worker."""
import os
import io
import json
import unittest
from uuid import uuid4

import psycopg
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb

from careerbrain.db import migrate, tenant_pool
from careerbrain.api import ResumeAPI
from careerbrain.auth import Denied
from careerbrain.resume import (DeterministicPdfExtractor, EphemeralResumeStore, ResumeRejected,
                                ResumeService, assert_ephemeral_runtime)
from tools.contracts import ContractError, validate, validate_evidence

DB = os.environ['NEXT_TEST_DATABASE']
SOCKET = os.environ['NEXT_TEST_SOCKET']
assert DB.startswith('cbn_test_') and os.environ.get('NEXT_DISPOSABLE_CI') == '1'


def connect(role='postgres'):
    return psycopg.connect(dbname=DB, user=role, host=SOCKET, autocommit=True)


def pdf(text='Python'):
    return ('%PDF-1.4\n1 0 obj <</Type /Page>> endobj\nBT (' + text + ') Tj ET\n%%EOF').encode()


class ResumeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with connect('cb_migrator') as conn:
            migrate(conn, target=7)
            migrate(conn, target=7)
        cls.api_pool = tenant_pool(make_conninfo(dbname=DB, user='cb_api', host=SOCKET), max_size=6)
        cls.worker_pool = tenant_pool(make_conninfo(dbname=DB, user='cb_private_worker', host=SOCKET), max_size=6)
        cls.api_pool.wait(timeout=5); cls.worker_pool.wait(timeout=5)

    @classmethod
    def tearDownClass(cls):
        cls.api_pool.close(); cls.worker_pool.close()

    def setUp(self):
        self.admin = connect(); self.addCleanup(self.admin.close)
        self.admin.execute('TRUNCATE private.resume_requests,queue.private_jobs,private.profiles RESTART IDENTITY CASCADE')
        self.tenants = []
        for _ in range(2):
            with connect('cb_auth') as conn:
                self.tenants.append(conn.execute('SELECT * FROM identity.provision(%s,%s)',
                                    ('https://accounts.google.com', 'resume-' + str(uuid4()))).fetchone())
        self.tenant, self.other = self.tenants
        self.store = EphemeralResumeStore()
        self.service = ResumeService(self.api_pool, self.worker_pool, self.store)

    def metadata(self, request=None, document=None):
        document = document or pdf()
        return {'schema_version': 'careerbrain.resume-upload.v1', 'request_id': request or 'resume-' + uuid4().hex,
                'content_type': 'application/pdf', 'content_length': len(document), 'consent_version': 'consent-v1'}

    def upload(self, document=None, request=None, tenant=None):
        document = document or pdf(); metadata = self.metadata(request, document)
        return self.service.upload(str((tenant or self.tenant)[1]), metadata, document, metadata['request_id'])

    def row(self, job):
        return self.admin.execute('SELECT state,generation,deletion_epoch,temporary_handle,attempts FROM queue.private_jobs WHERE id=%s',
                                  (job['job_id'],)).fetchone()

    def test_memory_swap_core_proof_and_schema_has_no_raw_columns(self):
        assert_ephemeral_runtime()
        columns = self.admin.execute("SELECT column_name FROM information_schema.columns WHERE table_schema IN ('private','queue')").fetchall()
        self.assertFalse({name for (name,) in columns} & {'resume_text','raw_resume','file_bytes','pdf','prompt'})
        self.assertNotIn('raw', self.admin.execute("SELECT pg_get_functiondef(p.oid) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='private' AND p.proname='create_resume_job'").fetchone()[0].lower())

    def test_success_persists_structured_profile_then_removes_all_temporary_bytes(self):
        original = self.tenant[2]
        job = self.upload(pdf('Experiência com Python e instalações elétricas'))
        handle = self.row(job)[3]
        self.assertIn(handle, self.store)
        self.assertEqual(self.service.process_once(), 'READY')
        self.assertNotIn(handle, self.store)
        profile = self.admin.execute('SELECT profile_version,generation,status,attributes,extractor_version FROM private.profiles WHERE tenant_id=%s',
                                     (self.tenant[1],)).fetchone()
        value = {'schema_version':'careerbrain.profile.v2','tenant_id':str(self.tenant[1]),'profile_version':profile[0],
                 'generation':profile[1],'status':profile[2],'attributes':profile[3],
                 'extractor_version':profile[4],'taxonomy_version':'professional-v1'}
        validate('private-profile-v2', value)
        self.assertEqual(self.admin.execute('SELECT account_created_at FROM identity.accounts WHERE id=%s',(self.tenant[0],)).fetchone()[0], original)

    def test_latest_resume_status_is_tenant_scoped_and_tracks_completion(self):
        self.assertIsNone(self.service.latest_status(str(self.tenant[1])))
        first = self.upload(pdf('Python'))
        self.assertEqual(self.service.latest_status(str(self.tenant[1])), first)
        self.assertIsNone(self.service.latest_status(str(self.other[1])))
        self.assertEqual(self.service.process_once(), 'READY')
        self.assertEqual(self.service.latest_status(str(self.tenant[1]))['status'], 'READY')
        second = self.upload(pdf('enfermagem'))
        self.assertEqual(self.service.latest_status(str(self.tenant[1])), second)
        self.assertIsNone(self.service.latest_status(str(self.other[1])))

    def test_uncertain_is_versioned_empty_attributes_not_a_fictitious_unknown(self):
        job = self.upload(pdf('Texto profissional sem frase reconhecida'))
        self.assertEqual(self.service.process_once(), 'UNCERTAIN')
        status, attributes = self.admin.execute('SELECT status,attributes FROM private.profiles WHERE tenant_id=%s',(self.tenant[1],)).fetchone()
        value = {'schema_version':'careerbrain.profile.v2','tenant_id':str(self.tenant[1]),'profile_version':1,
                 'generation':1,'status':status,'attributes':attributes,'extractor_version':'deterministic-pdf-v1',
                 'taxonomy_version':'professional-v1'}
        validate('private-profile-v2', value)
        self.assertEqual(attributes, [])
        legacy = dict(value, schema_version='careerbrain.profile.v1')
        with self.assertRaises(ContractError): validate('private-profile', legacy)

    def test_defensive_pdf_limits_and_invalid_upload_leave_no_job_or_temporary(self):
        bad = [b'not a pdf', pdf('x')[:-5], pdf('x /JavaScript'),
               b'%PDF-1.4\n' + b'/Type /Page\n' * 51 + b'(x) Tj\n%%EOF',
               b'%PDF-1.4\n1 0 obj <</Type /Page>>\n(' + b'x' * 200_001 + b') Tj\n%%EOF']
        for document in bad:
            with self.subTest(size=len(document)), self.assertRaises(ResumeRejected):
                self.upload(document)
        self.assertEqual(self.admin.execute("SELECT count(*) FROM queue.private_jobs WHERE kind='RESUME'").fetchone()[0], 0)
        self.assertEqual(len(self.store._entries), 0)

    def test_same_request_replays_and_new_request_advances_generation_without_changing_cutoff(self):
        document = pdf('Python')
        request = 'same-' + uuid4().hex
        first = self.upload(document, request)
        second = self.upload(document, request)
        self.assertEqual(first, second)
        created = self.tenant[2]
        replacement = self.upload(pdf('enfermagem'))
        self.assertEqual((self.row(first)[1], self.row(replacement)[1]), (1, 2))
        self.assertEqual(self.admin.execute('SELECT account_created_at FROM identity.accounts WHERE id=%s',(self.tenant[0],)).fetchone()[0], created)

    def test_delayed_result_cannot_overwrite_new_generation(self):
        old = self.upload(pdf('Python'))
        old_claim = self.service.claim(); self.assertEqual(str(old_claim.job_id), old['job_id'])
        newer = self.upload(pdf('enfermagem'))
        # The held lease is fenced by the new account generation before completion.
        status, attrs = self.service.extractor.profile(self.store.get(old_claim.handle))
        self.assertEqual(self.service._call('private.complete_resume_job', old_claim, status, Jsonb(attrs),
                                            'deterministic-pdf-v1', 'professional-v1'), 'CANCELLED')
        self.store.delete(old_claim.handle)
        self.assertEqual(self.service.process_once(), 'READY')
        profile = self.admin.execute('SELECT generation,attributes FROM private.profiles WHERE tenant_id=%s',(self.tenant[1],)).fetchone()
        self.assertEqual(profile[0], 2)
        self.assertIn('enfermagem', str(profile[1]))
        self.assertEqual(self.row(newer)[0], 'DONE')

    def test_cancel_lost_temp_expiry_and_restart_never_save_old_content(self):
        cancelled = self.upload(pdf('Python'))
        handle = self.row(cancelled)[3]
        self.assertTrue(self.service.cancel(str(self.tenant[1]), cancelled['job_id']))
        self.assertNotIn(handle, self.store); self.assertEqual(self.row(cancelled)[0], 'CANCELLED')
        lost = self.upload(pdf('enfermagem'))
        self.store.delete(self.row(lost)[3])
        self.assertEqual(self.service.process_once(), 'EXPIRED')
        expired = self.upload(pdf('Python'))
        self.admin.execute("UPDATE queue.private_jobs SET created_at=transaction_timestamp()-interval '15 minutes', expires_at=transaction_timestamp()-interval '1 second' WHERE id=%s",(expired['job_id'],))
        self.assertGreaterEqual(self.service.sweep(), 1)
        self.assertEqual(self.row(expired)[0], 'EXPIRED')
        restarted = self.upload(pdf('Python'))
        recovered = ResumeService(self.api_pool, self.worker_pool, EphemeralResumeStore())
        self.assertEqual(recovered.process_once(), 'EXPIRED')
        self.assertEqual(self.row(restarted)[0], 'EXPIRED')
        self.assertEqual(self.admin.execute('SELECT count(*) FROM private.profiles WHERE tenant_id=%s',(self.tenant[1],)).fetchone()[0], 0)

    def test_failure_retries_three_times_then_cleans_without_profile(self):
        class Broken(DeterministicPdfExtractor):
            def profile(self, document): raise RuntimeError('synthetic interruption')
        service = ResumeService(self.api_pool, self.worker_pool, self.store, Broken())
        job = self.upload(pdf('Python'))
        handle = self.row(job)[3]
        for expected in ('RETRY','RETRY','FAILED'):
            self.assertEqual(service.process_once(), expected)
            self.admin.execute("UPDATE queue.private_jobs SET available_at=transaction_timestamp()-interval '1 second' WHERE id=%s",(job['job_id'],))
        self.assertNotIn(handle, self.store)
        self.assertEqual(self.row(job)[0], 'FAILED')
        self.assertEqual(self.admin.execute('SELECT count(*) FROM private.profiles WHERE tenant_id=%s',(self.tenant[1],)).fetchone()[0], 0)

    def test_invalid_structured_result_is_not_persisted(self):
        class Invalid(DeterministicPdfExtractor):
            def profile(self, document):
                return 'READY', [{'name':'skill','value':'invented','basis':'explicit','confidence':1,'evidence':[]}]
        service = ResumeService(self.api_pool, self.worker_pool, self.store, Invalid())
        job = self.upload(pdf('Python'))
        self.assertEqual(service.process_once(), 'FAILED')
        self.assertNotIn(self.row(job)[3], self.store)
        self.assertEqual(self.admin.execute('SELECT count(*) FROM private.profiles WHERE tenant_id=%s',(self.tenant[1],)).fetchone()[0], 0)

    def test_cross_user_job_status_and_cancel_are_isolated(self):
        job = self.upload(pdf('Python'))
        self.assertIsNone(self.service.status(str(self.other[1]), job['job_id']))
        self.assertFalse(self.service.cancel(str(self.other[1]), job['job_id']))
        self.assertEqual(self.row(job)[0], 'READY')

    def test_authenticated_wsgi_upload_accepts_only_bounded_multipart(self):
        class Auth:
            def identity(_, token):
                if token != 'synthetic-access': raise Denied()
                return {'tenant_id': str(self.tenant[1])}
        class Identity: service = Auth()
        api = ResumeAPI(Identity(), self.service)
        document = pdf('Python')
        metadata = self.metadata('http-' + uuid4().hex, document)
        boundary = b'synthetic-boundary'
        raw = (b'--' + boundary + b'\r\nContent-Disposition: form-data; name="metadata"\r\n\r\n' +
               json.dumps(metadata).encode() + b'\r\n--' + boundary +
               b'\r\nContent-Disposition: form-data; name="file"; filename="resume.pdf"\r\nContent-Type: application/pdf\r\n\r\n' +
               document + b'\r\n--' + boundary + b'--\r\n')
        def request(token):
            received=[]
            body=b''.join(api({'REQUEST_METHOD':'POST','PATH_INFO':'/v1/me/resume',
                               'HTTP_AUTHORIZATION':'Bearer '+token,
                               'HTTP_IDEMPOTENCY_KEY':metadata['request_id'],
                               'CONTENT_TYPE':'multipart/form-data; boundary=synthetic-boundary',
                               'CONTENT_LENGTH':str(len(raw)),'wsgi.input':io.BytesIO(raw)},
                              lambda status, headers: received.append(status)))
            return received[0], json.loads(body)
        self.assertEqual(request('wrong')[0], '401 Unauthorized')
        self.assertEqual(request('synthetic-access')[0], '202 Accepted')


if __name__ == '__main__':
    unittest.main(verbosity=2)
