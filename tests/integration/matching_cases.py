"""Private matching tests. Run only in the networkless disposable PostgreSQL worker."""
from datetime import timedelta
import os
import unittest
from uuid import uuid4

import psycopg
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb

from careerbrain.db import migrate, tenant_pool, tenant_transaction
from careerbrain.matching import MatchService

DB=os.environ['NEXT_TEST_DATABASE']; SOCKET=os.environ['NEXT_TEST_SOCKET']
assert DB.startswith('cbn_test_') and os.environ.get('NEXT_DISPOSABLE_CI') == '1'

def connect(role='postgres'):
    return psycopg.connect(dbname=DB,user=role,host=SOCKET,autocommit=True)


class MatchingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with connect('cb_migrator') as c: migrate(c,target=8)
        cls.worker=tenant_pool(make_conninfo(dbname=DB,user='cb_private_worker',host=SOCKET),max_size=4)
        cls.worker.wait(timeout=5)

    @classmethod
    def tearDownClass(cls): cls.worker.close()

    def setUp(self):
        self.admin=connect(); self.addCleanup(self.admin.close)
        self.admin.execute('TRUNCATE private.match_requests,private.recommendations,private.feed,private.feed_counters,queue.private_jobs,private.profiles RESTART IDENTITY CASCADE')
        self.admin.execute("INSERT INTO ops.classifier_policy(singleton,taxonomy_version,model_version,prompt_version) VALUES(true,'professional-v1','synthetic-v1','prompt-v1') ON CONFLICT(singleton) DO UPDATE SET taxonomy_version=EXCLUDED.taxonomy_version,model_version=EXCLUDED.model_version,prompt_version=EXCLUDED.prompt_version")
        self.tenants=[]
        for name in ('matching-a','matching-b'):
            with connect('cb_auth') as c:
                self.tenants.append(c.execute('SELECT * FROM identity.provision(%s,%s)',('https://accounts.google.com',name+'-'+uuid4().hex)).fetchone())
        self.tenant,self.other=self.tenants
        attribute={'name':'skill','value':'Python','basis':'explicit','confidence':1,'evidence':[{'field':'synthetic','quote':'Python','start':0,'end':6}]}
        for tenant in self.tenants:
            self.admin.execute("INSERT INTO private.profiles(tenant_id,profile_version,generation,deletion_epoch,status,attributes,extractor_version,taxonomy_version) VALUES(%s,1,0,0,'READY',%s,'synthetic','professional-v1')",(tenant[1],Jsonb([attribute])))
        self.service=MatchService(self.worker,self.worker)

    def event(self,published,*,observed=None,state='ACTIVE'):
        source,producer,authorization,evidence=[uuid4() for _ in range(4)]
        self.admin.execute('INSERT INTO catalog.sources VALUES(%s,%s)',(source,'synthetic matching source'))
        self.admin.execute('INSERT INTO catalog.producers(id) VALUES(%s)',(producer,))
        self.admin.execute('INSERT INTO catalog.authorizations VALUES(%s,%s,%s,true)',(authorization,producer,source))
        self.admin.execute('INSERT INTO catalog.evidence VALUES(%s,%s,%s,%s)',(evidence,source,authorization,'a'*64))
        content={'title':'Synthetic Python role','organization':'Synthetic','description':'Python role '+('x'*80),'requirements':['Python'],'modality':'remote','location':'Recife','employment_type':'employee','access':{'kind':'https','value':'https://example.org/jobs/synthetic'}}
        vacancy=self.admin.execute('INSERT INTO catalog.vacancies(source_id,source_vacancy_id,content) VALUES(%s,%s,%s) RETURNING id',(source,uuid4().hex,Jsonb(content))).fetchone()[0]
        observed=observed or published
        event=self.admin.execute("INSERT INTO catalog.publication_events(vacancy_id,source_id,source_event_id,kind,published_at,observed_at,received_at,evidence_id,state) VALUES(%s,%s,%s,'original',%s,%s,%s,%s,%s) RETURNING id",(vacancy,source,uuid4().hex,published,observed,observed,evidence,state)).fetchone()[0]
        result={'schema_version':'careerbrain.semantics.v1','status':'READY','attributes':[{'name':'skill','value':'Python','basis':'explicit','confidence':1,'evidence':[{'field':'description','quote':'Python','start':0,'end':6}]}]}
        cache=self.admin.execute("INSERT INTO catalog.classification_cache(vacancy_id,content_version,content_digest,taxonomy_version,model_version,prompt_version,status,result) VALUES(%s,1,%s,'professional-v1','synthetic-v1','prompt-v1','READY',%s) RETURNING id",(vacancy,'b'*64,Jsonb(result))).fetchone()[0]
        self.admin.execute('INSERT INTO catalog.event_classifications(event_id,cache_id) VALUES(%s,%s)',(event,cache))
        return event

    def test_cutoff_equal_after_late_observation_and_evidenced_affinity(self):
        created=self.tenant[2]
        before=self.event(created-timedelta(microseconds=1),observed=created+timedelta(days=1))
        equal=self.event(created)
        after=self.event(created+timedelta(microseconds=1))
        self.assertIsNone(self.service.schedule(str(self.tenant[1]),str(before)))
        first=self.service.schedule(str(self.tenant[1]),str(equal)); self.assertIsNotNone(first)
        self.assertEqual(first,self.service.schedule(str(self.tenant[1]),str(equal)))
        self.assertEqual(self.service.process_once(),'READY')
        self.assertIsNotNone(self.service.schedule(str(self.tenant[1]),str(after)))
        self.assertEqual(self.service.process_once(),'READY')
        with tenant_transaction(self.worker,str(self.tenant[1])) as c:
            rows=c.execute('SELECT event_id,affinity,confidence,reasons FROM private.current_recommendations ORDER BY event_id').fetchall()
        self.assertEqual(len(rows),2)
        self.assertTrue(all(row[1:]==(1,1,['EVIDENCED_AFFINITY']) for row in rows))

    def test_unknown_is_eligible_without_score_and_lifecycle_removes_projection(self):
        event=self.event(self.tenant[2])
        self.admin.execute("UPDATE catalog.classification_cache SET status='UNCERTAIN',result=%s",(Jsonb({'schema_version':'careerbrain.semantics.v1','status':'UNCERTAIN','attributes':[]}),))
        self.assertIsNotNone(self.service.schedule(str(self.tenant[1]),str(event)))
        self.assertEqual(self.service.process_once(),'READY')
        with tenant_transaction(self.worker,str(self.tenant[1])) as c:
            self.assertEqual(c.execute('SELECT affinity,confidence,reasons FROM private.current_recommendations').fetchone(),(None,None,['REQUIREMENT_UNKNOWN']))
        self.admin.execute("UPDATE catalog.publication_events SET state='CLOSED' WHERE id=%s",(event,))
        self.assertIsNone(self.service.schedule(str(self.tenant[1]),str(event)))
        with tenant_transaction(self.worker,str(self.tenant[1])) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM private.current_recommendations').fetchone()[0],0)
            self.assertEqual(c.execute("SELECT kind FROM private.feed ORDER BY sequence DESC LIMIT 1").fetchone()[0],'REMOVED')

    def test_fencing_policy_change_and_cross_tenant_access_do_not_leak_or_commit_stale_work(self):
        event=self.event(self.tenant[2])
        self.service.schedule(str(self.tenant[1]),str(event)); claim=self.service.claim(); self.assertIsNotNone(claim)
        self.admin.execute("UPDATE ops.matching_policy SET policy_version='matching-v2'")
        with tenant_transaction(self.worker,str(claim.tenant_id)) as c:
            self.assertEqual(c.execute('SELECT private.complete_match_job(%s,%s,%s,NULL,NULL,%s)',(claim.job_id,c.execute('SELECT lease_owner FROM queue.private_jobs WHERE id=%s',(claim.job_id,)).fetchone()[0],claim.fencing,['REQUIREMENT_UNKNOWN'])).fetchone()[0],'CANCELLED')
        with tenant_transaction(self.worker,str(self.other[1])) as c:
            self.assertEqual(c.execute('SELECT * FROM private.current_recommendations').fetchall(),[])
            self.assertEqual(c.execute('SELECT * FROM private.match_requests').fetchall(),[])


if __name__=='__main__': unittest.main(verbosity=2)
