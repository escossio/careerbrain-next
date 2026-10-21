"""Real PostgreSQL tests. Run only inside the isolated disposable worker job."""
import concurrent.futures
from datetime import timedelta
import os
import time
import unittest
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from careerbrain.db import bootstrap_disposable, migrate, MigrationError, tenant_pool, tenant_transaction

DB = os.environ['NEXT_TEST_DATABASE']
SOCKET = os.environ['NEXT_TEST_SOCKET']
assert DB.startswith('cbn_test_') and os.environ.get('NEXT_DISPOSABLE_CI') == '1'


def connect(role='postgres', database=DB):
    return psycopg.connect(dbname=database, user=role, host=SOCKET, autocommit=True)


class DatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with connect() as c:
            bootstrap_disposable(c)
        with connect('cb_migrator') as c:
            migrate(c, target=2)

    def setUp(self):
        self.admin = connect()
        self.addCleanup(self.admin.close)
        self.accounts = []
        for _ in range(2):
            with connect('cb_auth') as c:
                self.accounts.append(c.execute('SELECT * FROM identity.provision(%s,%s)',
                    ('https://accounts.google.com', 'synthetic-' + str(uuid4()))).fetchone())
        self.a, self.b = self.accounts
        self.pool = tenant_pool(make_conninfo(dbname=DB,user='cb_api',host=SOCKET),max_size=1)
        self.pool.wait(timeout=5)
        self.addCleanup(self.pool.close)
        for account in self.accounts:
            with tenant_transaction(self.pool, str(account[1])) as c:
                c.execute('''INSERT INTO private.profiles VALUES(%s,1,0,0,'[]','synthetic','synthetic')''', (account[1],))

    def event(self, published=None, *, previous=None, vacancy=None, received=None):
        source, producer, authorization, evidence = [uuid4() for _ in range(4)]
        published = published or self.admin.execute('SELECT clock_timestamp()').fetchone()[0]
        if vacancy is None:
            self.admin.execute('INSERT INTO catalog.sources VALUES(%s,%s)',(source,'synthetic source'))
            self.admin.execute('INSERT INTO catalog.producers(id) VALUES(%s)',(producer,))
            self.admin.execute('INSERT INTO catalog.authorizations VALUES(%s,%s,%s,true)',(authorization,producer,source))
            self.admin.execute('INSERT INTO catalog.evidence VALUES(%s,%s,%s,%s)',(evidence,source,authorization,'a'*64))
            vacancy=self.admin.execute("INSERT INTO catalog.vacancies(source_id,source_vacancy_id,content) VALUES(%s,%s,'{}') RETURNING id",(source,str(uuid4()))).fetchone()[0]
        else:
            source,authorization=self.admin.execute('''SELECT v.source_id,e.authorization_id FROM catalog.vacancies v
              JOIN catalog.evidence e ON e.source_id=v.source_id WHERE v.id=%s LIMIT 1''',(vacancy,)).fetchone()
            self.admin.execute('INSERT INTO catalog.evidence VALUES(%s,%s,%s,%s)',(evidence,source,authorization,'b'*64))
        event=self.admin.execute('''INSERT INTO catalog.publication_events(vacancy_id,source_id,source_event_id,kind,predecessor_id,published_at,observed_at,evidence_id,received_at)
          VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',
          (vacancy,source,str(uuid4()),'republication' if previous else 'original',previous,published,published,evidence,received or published)).fetchone()[0]
        return event,vacancy

    def test_real_runtime_roles_cannot_bypass_rls_or_escalate(self):
        for role in ['cb_api','cb_auth','cb_global_worker','cb_private_worker','cb_privacy']:
            with self.subTest(role=role),connect(role) as c:
                self.assertEqual(c.execute('SELECT current_user,session_user').fetchone(),(role,role))
                self.assertEqual(c.execute('SELECT rolsuper,rolbypassrls,rolcreaterole,rolcreatedb FROM pg_roles WHERE rolname=current_user').fetchone(),(False,False,False,False))
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):c.execute('SET ROLE cb_owner')
        with connect('cb_api') as c:
            for statement in ['ALTER TABLE private.profiles DISABLE ROW LEVEL SECURITY','TRUNCATE private.profiles',
                              'SELECT * FROM identity.external_identities','SELECT * FROM ops.deletion_ledger']:
                with self.subTest(statement=statement),self.assertRaises(psycopg.errors.InsufficientPrivilege):c.execute(statement)

    def test_rls_forced_on_every_tenant_table(self):
        rows=self.admin.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname IN ('identity','private') AND relkind='r'").fetchall()
        self.assertGreaterEqual(len(rows),9)
        self.assertTrue(all(x==(True,True) for x in rows))

    def test_missing_or_invalid_context_denies_reads_and_writes(self):
        with connect('cb_api') as c:
            self.assertEqual(c.execute('SELECT * FROM private.profiles').fetchall(),[])
            c.execute("SELECT set_config('careerbrain.tenant_id','invalid',false)")
            self.assertEqual(c.execute('SELECT * FROM private.profiles').fetchall(),[])
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                c.execute("INSERT INTO private.commands VALUES(%s,'test','request',%s,'{}')",(self.a[1],'a'*64))

    def test_cross_tenant_read_write_update_delete(self):
        with tenant_transaction(self.pool,str(self.a[1])) as c:
            self.assertEqual([r[0] for r in c.execute('SELECT tenant_id FROM private.profiles')],[self.a[1]])
            self.assertEqual(c.execute('UPDATE private.profiles SET profile_version=2 WHERE tenant_id=%s',(self.b[1],)).rowcount,0)
            self.assertEqual(c.execute('DELETE FROM private.profiles WHERE tenant_id=%s',(self.b[1],)).rowcount,0)
        with self.assertRaises(psycopg.errors.InsufficientPrivilege),tenant_transaction(self.pool,str(self.a[1])) as c:
            c.execute("INSERT INTO private.commands VALUES(%s,'test','cross',%s,'{}')",(self.b[1],'a'*64))

    def test_global_worker_has_no_private_access_and_api_no_catalog_write(self):
        with connect('cb_global_worker') as c:
            for q in ['SELECT * FROM private.profiles','SELECT * FROM identity.accounts','SELECT * FROM queue.private_jobs']:
                with self.subTest(query=q),self.assertRaises(psycopg.errors.InsufficientPrivilege):c.execute(q)
        with connect('cb_api') as c,self.assertRaises(psycopg.errors.InsufficientPrivilege):
            c.execute('INSERT INTO catalog.sources VALUES(%s,%s)',(uuid4(),'synthetic'))

    def test_private_worker_scoped_to_current_tenant(self):
        with connect('cb_private_worker') as c:
            self.assertEqual(c.execute('SELECT * FROM private.profiles').fetchall(),[])
            with c.transaction():
                c.execute("SELECT set_config('careerbrain.tenant_id',%s,true)",(str(self.b[1]),))
                self.assertEqual([r[0] for r in c.execute('SELECT tenant_id FROM private.profiles')],[self.b[1]])
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):c.execute('SELECT * FROM queue.catalog_jobs')

    def test_transaction_context_and_pool_reset_after_commit_and_error(self):
        with tenant_transaction(self.pool,str(self.a[1])) as c:
            c.execute("SELECT set_config('careerbrain.tenant_id',%s,false)",(str(self.a[1]),))
        # Pool's reset callback runs before a connection becomes available again.
        with self.pool.connection() as c:self.assertEqual(c.execute('SELECT * FROM private.profiles').fetchall(),[])
        with self.assertRaises(psycopg.errors.DivisionByZero),tenant_transaction(self.pool,str(self.a[1])) as c:c.execute('SELECT 1/0')
        with tenant_transaction(self.pool,str(self.b[1])) as c:
            self.assertEqual([r[0] for r in c.execute('SELECT tenant_id FROM private.profiles')],[self.b[1]])
        with self.pool.connection() as c:self.assertEqual(c.execute('SELECT * FROM private.profiles').fetchall(),[])

    def test_account_cutoff_immutable_and_profile_change_preserves_it(self):
        with self.assertRaises(psycopg.errors.CheckViolation):
            self.admin.execute("UPDATE identity.accounts SET account_created_at=account_created_at-interval '1 day' WHERE id=%s",(self.a[0],))
        with tenant_transaction(self.pool,str(self.a[1])) as c:c.execute('UPDATE private.profiles SET profile_version=2 WHERE tenant_id=%s',(self.a[1],))
        self.assertEqual(self.admin.execute('SELECT account_created_at FROM identity.accounts WHERE id=%s',(self.a[0],)).fetchone()[0],self.a[2])

    def test_concurrent_provisioning_is_stable(self):
        subject='synthetic-concurrent-'+str(uuid4())
        def provision(_):
            with connect('cb_auth') as c:return c.execute('SELECT * FROM identity.provision(%s,%s)',('https://accounts.google.com',subject)).fetchone()
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:results=list(executor.map(provision,range(8)))
        self.assertEqual(len(set(results)),1)
        self.assertEqual(self.admin.execute('SELECT count(*) FROM identity.external_identities WHERE subject=%s',(subject,)).fetchone()[0],1)

    def test_publication_before_equal_after_cutoff(self):
        before,_=self.event(self.a[2]-timedelta(microseconds=1));equal,_=self.event(self.a[2]);after,_=self.event(self.a[2]+timedelta(microseconds=1))
        with self.assertRaises(psycopg.errors.CheckViolation),tenant_transaction(self.pool,str(self.a[1])) as c:
            c.execute('INSERT INTO private.recommendations VALUES(%s,%s,1,%s,0.8)',(self.a[1],before,'synthetic'))
        with tenant_transaction(self.pool,str(self.a[1])) as c:
            for e in [equal,after]:c.execute('INSERT INTO private.recommendations VALUES(%s,%s,1,%s,0.8)',(self.a[1],e,'synthetic'))
            self.assertEqual(c.execute('SELECT count(*) FROM private.recommendations').fetchone()[0],2)
        self.admin.execute("UPDATE catalog.publication_events SET state='CLOSED' WHERE id=%s",(after,))
        with tenant_transaction(self.pool,str(self.a[1])) as c:self.assertEqual(c.execute('SELECT count(*) FROM private.recommendations').fetchone()[0],1)

    def test_publication_immutability_future_and_republication_constraints(self):
        event,vacancy=self.event()
        with self.assertRaises(psycopg.errors.CheckViolation):self.admin.execute("UPDATE catalog.publication_events SET published_at=published_at-interval '1 second' WHERE id=%s",(event,))
        future=self.admin.execute("SELECT clock_timestamp()+interval '1 day'").fetchone()[0]
        with self.assertRaises(psycopg.errors.CheckViolation):self.event(future,received=future+timedelta(days=1))
        when=self.admin.execute('SELECT published_at FROM catalog.publication_events WHERE id=%s',(event,)).fetchone()[0]
        with self.assertRaises(psycopg.errors.CheckViolation):self.event(when,previous=event,vacancy=vacancy)
        repub,_=self.event(previous=event,vacancy=vacancy)
        self.assertNotEqual(repub,event)
        self.admin.execute("UPDATE catalog.publication_events SET state='WITHDRAWN' WHERE id=%s",(event,))
        with self.assertRaises(psycopg.errors.CheckViolation):self.admin.execute("UPDATE catalog.publication_events SET state='ACTIVE' WHERE id=%s",(event,))

    def test_stale_profile_generation_or_epoch_rejected(self):
        for column in ['generation','deletion_epoch']:
            with self.subTest(column=column),self.assertRaises(psycopg.errors.CheckViolation),tenant_transaction(self.pool,str(self.a[1])) as c:
                c.execute(sql.SQL('UPDATE private.profiles SET {}=1,profile_version=2 WHERE tenant_id=%s').format(sql.Identifier(column)),(self.a[1],))

    def test_private_queue_contains_only_handles_and_has_ttl(self):
        with tenant_transaction(self.pool,str(self.a[1])) as c:
            c.execute("INSERT INTO queue.private_jobs(tenant_id,kind,temporary_handle,generation,deletion_epoch,expires_at) VALUES(%s,'RESUME',%s,0,0,transaction_timestamp()+interval '15 minutes')",(self.a[1],uuid4()))
        with self.assertRaises(psycopg.errors.CheckViolation),tenant_transaction(self.pool,str(self.a[1])) as c:
            c.execute("INSERT INTO queue.private_jobs(tenant_id,kind,temporary_handle,generation,deletion_epoch,expires_at) VALUES(%s,'RESUME',%s,0,0,transaction_timestamp()+interval '16 minutes')",(self.a[1],uuid4()))
        with connect('cb_api') as c,self.assertRaises(psycopg.errors.UndefinedColumn):c.execute("INSERT INTO queue.private_jobs(raw_resume) VALUES('synthetic')")

    def test_outbox_atomicity_and_job_idempotence(self):
        event,_=self.event()
        with connect('cb_global_worker') as c:
            with self.assertRaises(RuntimeError),c.transaction():
                c.execute("INSERT INTO queue.catalog_outbox(event_id,event_version,kind) VALUES(%s,'v1','PUBLISHED')",(event,))
                c.execute("INSERT INTO queue.catalog_jobs(event_id,task_version) VALUES(%s,'v1')",(event,))
                raise RuntimeError('synthetic crash')
            self.assertEqual(c.execute('SELECT count(*) FROM queue.catalog_outbox WHERE event_id=%s',(event,)).fetchone()[0],0)
            with c.transaction():
                c.execute("INSERT INTO queue.catalog_outbox(event_id,event_version,kind) VALUES(%s,'v1','PUBLISHED')",(event,))
                c.execute("INSERT INTO queue.catalog_jobs(event_id,task_version) VALUES(%s,'v1')",(event,))
            with self.assertRaises(psycopg.errors.UniqueViolation):c.execute("INSERT INTO queue.catalog_jobs(event_id,task_version) VALUES(%s,'v1')",(event,))

    def test_feed_sequence_serializes_per_tenant_until_commit(self):
        event,_=self.event();c1=connect('cb_api');c2=connect('cb_api');self.addCleanup(c1.close);self.addCleanup(c2.close)
        executor=concurrent.futures.ThreadPoolExecutor(max_workers=1);self.addCleanup(executor.shutdown)
        def insert_second():
            with c2.transaction():
                c2.execute("SELECT set_config('careerbrain.tenant_id',%s,true)",(str(self.a[1]),))
                return c2.execute("INSERT INTO private.feed VALUES(%s,0,%s,'UPSERT',DEFAULT) RETURNING sequence",(self.a[1],event)).fetchone()[0]
        with c1.transaction():
            c1.execute("SELECT set_config('careerbrain.tenant_id',%s,true)",(str(self.a[1]),))
            first=c1.execute("INSERT INTO private.feed VALUES(%s,0,%s,'UPSERT',DEFAULT) RETURNING sequence",(self.a[1],event)).fetchone()[0]
            second=executor.submit(insert_second);time.sleep(.1);self.assertFalse(second.done())
        self.assertEqual((first,second.result(timeout=3)),(1,2))

    def test_migration_reapply_concurrent_checksum_and_compatible_rollback(self):
        def apply(_):
            with connect('cb_migrator') as c:migrate(c,target=2)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:list(executor.map(apply,range(2)))
        count=self.admin.execute('SELECT count(*) FROM private.profiles').fetchone()[0]
        with connect('cb_migrator') as c:
            migrate(c,target=1);self.assertEqual(self.admin.execute('SELECT count(*) FROM private.profiles').fetchone()[0],count);migrate(c,target=2)
            self.assertEqual(c.execute('SELECT current_user').fetchone()[0],'cb_migrator')
        checksum=self.admin.execute('SELECT checksum FROM ops.schema_migrations WHERE version=1').fetchone()[0]
        self.admin.execute("UPDATE ops.schema_migrations SET checksum='changed' WHERE version=1")
        try:
            with connect('cb_migrator') as c,self.assertRaises(MigrationError):migrate(c,target=2)
        finally:self.admin.execute('UPDATE ops.schema_migrations SET checksum=%s WHERE version=1',(checksum,))
        with connect('cb_migrator') as c,self.assertRaises(MigrationError):migrate(c,target=0)

    def test_deletion_denies_reads_jobs_and_login_immediately(self):
        with tenant_transaction(self.pool,str(self.a[1])) as c:c.execute('SELECT ops.begin_deletion()')
        with tenant_transaction(self.pool,str(self.a[1])) as c:self.assertEqual(c.execute('SELECT * FROM private.profiles').fetchall(),[])
        subject=self.admin.execute('SELECT subject FROM identity.external_identities WHERE account_id=%s',(self.a[0],)).fetchone()[0]
        with connect('cb_auth') as c,self.assertRaises(psycopg.errors.InsufficientPrivilege):c.execute('SELECT * FROM identity.provision(%s,%s)',('https://accounts.google.com',subject))
        with self.assertRaises(psycopg.errors.CheckViolation):self.admin.execute("UPDATE identity.accounts SET state='ACTIVE' WHERE id=%s",(self.a[0],))


if __name__ == '__main__':
    unittest.main(verbosity=2)
