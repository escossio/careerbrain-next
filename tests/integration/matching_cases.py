"""Private matching tests. Run only in the networkless disposable PostgreSQL worker."""
from datetime import timedelta
import concurrent.futures
import os
import unittest
from uuid import uuid4

import psycopg
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb

from careerbrain.db import migrate, tenant_pool, tenant_transaction
from careerbrain.matching import MatchService
from careerbrain.mobile import Conflict, MobileService
from tools.contracts import ContractError, validate_requirement_evidence

DB=os.environ['NEXT_TEST_DATABASE']; SOCKET=os.environ['NEXT_TEST_SOCKET']
assert DB.startswith('cbn_test_') and os.environ.get('NEXT_DISPOSABLE_CI') == '1'

def connect(role='postgres'):
    return psycopg.connect(dbname=DB,user=role,host=SOCKET,autocommit=True)


class MatchingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with connect('cb_migrator') as c: migrate(c,target=10)
        cls.worker=tenant_pool(make_conninfo(dbname=DB,user='cb_private_worker',host=SOCKET),max_size=4)
        cls.api=tenant_pool(make_conninfo(dbname=DB,user='cb_api',host=SOCKET),max_size=4)
        cls.worker.wait(timeout=5)
        cls.api.wait(timeout=5)

    @classmethod
    def tearDownClass(cls): cls.worker.close(); cls.api.close()

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
        self.mobile=MobileService(self.api)

    def event(self,published,*,observed=None,state='ACTIVE',classification_result=None):
        source,producer,authorization,evidence=[uuid4() for _ in range(4)]
        self.admin.execute('INSERT INTO catalog.sources VALUES(%s,%s)',(source,'synthetic matching source'))
        self.admin.execute('INSERT INTO catalog.producers(id) VALUES(%s)',(producer,))
        self.admin.execute('INSERT INTO catalog.authorizations VALUES(%s,%s,%s,true)',(authorization,producer,source))
        self.admin.execute('INSERT INTO catalog.evidence VALUES(%s,%s,%s,%s)',(evidence,source,authorization,'a'*64))
        content={'title':'Synthetic Python role','organization':'Synthetic','description':'Python role '+('x'*80),'requirements':['Python'],'modality':'remote','location':'Recife','employment_type':'employee','access':{'kind':'https','value':'https://example.org/jobs/synthetic'}}
        vacancy=self.admin.execute('INSERT INTO catalog.vacancies(source_id,source_vacancy_id,content) VALUES(%s,%s,%s) RETURNING id',(source,uuid4().hex,Jsonb(content))).fetchone()[0]
        observed=observed or published
        event=self.admin.execute("INSERT INTO catalog.publication_events(vacancy_id,source_id,source_event_id,kind,published_at,observed_at,received_at,evidence_id,state) VALUES(%s,%s,%s,'original',%s,%s,%s,%s,%s) RETURNING id",(vacancy,source,uuid4().hex,published,observed,observed,evidence,state)).fetchone()[0]
        result=classification_result or {'schema_version':'careerbrain.semantics.v1','status':'READY','attributes':[{'name':'skill','value':'Python','basis':'explicit','confidence':1,'evidence':[{'field':'description','quote':'Python','start':0,'end':6}]}]}
        cache=self.admin.execute("INSERT INTO catalog.classification_cache(vacancy_id,content_version,content_digest,taxonomy_version,model_version,prompt_version,status,result) VALUES(%s,1,%s,'professional-v1','synthetic-v1','prompt-v1','READY',%s) RETURNING id",(vacancy,'b'*64,Jsonb(result))).fetchone()[0]
        self.admin.execute('INSERT INTO catalog.event_classifications(event_id,cache_id) VALUES(%s,%s)',(event,cache))
        return event

    def test_mobile_recommendations_sql_join_returns_published_matches(self):
        """Guards against selecting available_at from the wrong projection view."""
        initial=self.mobile.recommendations(str(self.tenant[1]))
        self.assertEqual(initial['items'],[])
        event=self.event(self.tenant[2])
        self.assertIsNotNone(self.service.schedule(str(self.tenant[1]),str(event)))
        self.assertEqual(self.service.process_once(),'READY')
        result=self.mobile.recommendations(str(self.tenant[1]))
        self.assertEqual(len(result['items']),1)
        self.assertEqual(result['items'][0]['title'],'Synthetic Python role')
        self.assertEqual(result['items'][0]['match']['affinity'],1.0)
        self.assertEqual(self.mobile.recommendations(str(self.other[1]))['items'],[])

    def test_cutoff_equal_after_late_observation_and_evidenced_affinity(self):
        created=self.tenant[2]
        before=self.event(created-timedelta(microseconds=1),observed=created+timedelta(microseconds=1))
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

    def test_verified_mandatory_requirement_and_explicit_negative_hide_recommendation(self):
        requirement={'requirement_id':'license-python','name':'license','value':'Python License',
                     'evidence':{'source_version':'vacancy-content-v2','field':'requirements/0',
                                 'quote':'Python License','start':0,'end':14}}
        attestation={'requirement_id':'license-python','name':'license','value':'Python License',
                     'state':'NOT_MET','evidence':{'source_version':'profile-source-v2','field':'attestation',
                                                    'quote':'I do not hold a Python License','start':0,'end':30}}
        validate_requirement_evidence('Python License',requirement)
        validate_requirement_evidence('I do not hold a Python License',attestation)
        self.admin.execute("UPDATE private.profiles SET profile_version=profile_version+1,contract_version='careerbrain.profile.v3',source_version=%s,negative_attestations=%s WHERE tenant_id=%s",
                           ('profile-source-v2',Jsonb([attestation]),self.tenant[1]))
        result={'schema_version':'careerbrain.semantics.v2','status':'READY','attributes':[],
                'source_version':'vacancy-content-v2','mandatory_requirements':[requirement]}
        event=self.event(self.tenant[2],classification_result=result)
        self.assertIsNotNone(self.service.schedule(str(self.tenant[1]),str(event)))
        self.assertEqual(self.service.process_once(),'READY')
        row=self.admin.execute('SELECT reasons,requirement_proofs FROM private.recommendations').fetchone()
        self.assertEqual(row,(['REQUIREMENT_UNMET'],[{'mandatory_requirement':requirement,
                                                       'negative_attestation':attestation}]))
        with tenant_transaction(self.worker,str(self.tenant[1])) as c:
            self.assertEqual(c.execute('SELECT * FROM private.current_recommendations').fetchall(),[])

    def test_missing_or_forged_negative_attestation_stays_unknown(self):
        requirement={'requirement_id':'license-python','name':'license','value':'Python License',
                     'evidence':{'source_version':'vacancy-content-v2','field':'requirements/0',
                                 'quote':'Python License','start':0,'end':14}}
        result={'schema_version':'careerbrain.semantics.v2','status':'READY','attributes':[],
                'source_version':'vacancy-content-v2','mandatory_requirements':[requirement]}
        self.admin.execute("UPDATE private.profiles SET profile_version=profile_version+1,contract_version='careerbrain.profile.v3',source_version='profile-source-v2',negative_attestations='[]'::jsonb WHERE tenant_id=%s",(self.tenant[1],))
        absent=self.event(self.tenant[2],classification_result=result)
        self.assertIsNotNone(self.service.schedule(str(self.tenant[1]),str(absent)))
        self.assertEqual(self.service.process_once(),'READY')
        self.assertEqual(self.admin.execute('SELECT reasons FROM private.recommendations WHERE event_id=%s',(absent,)).fetchone()[0],['REQUIREMENT_UNKNOWN'])
        forged={'requirement_id':'license-python','name':'license','value':'Python License','state':'NOT_MET',
                'evidence':{'source_version':'wrong-profile-source','field':'attestation',
                            'quote':'invented attestation','start':0,'end':19}}
        with self.assertRaises(ContractError):
            validate_requirement_evidence('I do not hold a Python License',forged)
        self.admin.execute('UPDATE private.profiles SET profile_version=profile_version+1,negative_attestations=%s WHERE tenant_id=%s',(Jsonb([forged]),self.tenant[1]))
        forged_event=self.event(self.tenant[2],classification_result=result)
        self.assertIsNotNone(self.service.schedule(str(self.tenant[1]),str(forged_event)))
        self.assertEqual(self.service.process_once(),'READY')
        self.assertEqual(self.admin.execute('SELECT reasons FROM private.recommendations WHERE event_id=%s',(forged_event,)).fetchone()[0],['REQUIREMENT_UNKNOWN'])

    def test_mobile_sync_snapshots_keep_late_availability_for_both_devices(self):
        first=self.event(self.tenant[2]); self.service.schedule(str(self.tenant[1]),str(first)); self.assertEqual(self.service.process_once(),'READY')
        device_a=self.mobile.changes(str(self.tenant[1]),limit=1)
        self.assertEqual(device_a['items'][0]['kind'],'AVAILABLE')
        end=self.mobile.changes(str(self.tenant[1]),device_a['next_cursor'],1)
        self.assertEqual(end['items'],[])
        second=self.event(self.tenant[2]); self.service.schedule(str(self.tenant[1]),str(second)); self.assertEqual(self.service.process_once(),'READY')
        device_b=self.mobile.changes(str(self.tenant[1]),limit=10)
        self.assertEqual(len(device_b['items']),2)
        later=self.mobile.changes(str(self.tenant[1]),end['next_cursor'],10)
        self.assertEqual([x['publication_event_id'] for x in later['items']],[str(second)])

    def test_application_cas_replay_and_concurrent_devices(self):
        event=self.event(self.tenant[2]); command={'schema_version':'careerbrain.application.v1','request_id':'save-'+uuid4().hex,'publication_event_id':str(event),'expected_version':0,'state':'SAVED'}
        self.mobile.application(str(self.tenant[1]),command); self.mobile.application(str(self.tenant[1]),command)
        changed=dict(command,state='APPLIED')
        with self.assertRaises(Conflict): self.mobile.application(str(self.tenant[1]),changed)
        def write(state):
            value={'schema_version':'careerbrain.application.v1','request_id':state.lower()+'-'+uuid4().hex,'publication_event_id':str(event),'expected_version':1,'state':state}
            try: self.mobile.application(str(self.tenant[1]),value); return True
            except Conflict: return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor: outcome=list(executor.map(write,('APPLIED','WITHDRAWN')))
        self.assertEqual(sum(outcome),1)
        self.assertEqual(self.admin.execute('SELECT version,count(*) FROM private.applications GROUP BY version').fetchone(),(2,1))

    def test_deletion_purges_private_state_and_ledger_sanitizes_restore(self):
        event=self.event(self.tenant[2]); self.service.schedule(str(self.tenant[1]),str(event)); self.service.process_once()
        receipt=self.mobile.delete(str(self.tenant[1]),'delete-'+uuid4().hex)
        self.assertEqual(receipt['state'],'ACTIVE_DATA_REMOVED')
        self.assertEqual(self.admin.execute('SELECT count(*) FROM private.tenants WHERE id=%s',(self.tenant[1],)).fetchone()[0],0)
        self.assertEqual(self.admin.execute('SELECT count(*) FROM private.recommendations WHERE tenant_id=%s',(self.tenant[1],)).fetchone()[0],0)
        self.assertIsNotNone(self.mobile.receipt(receipt['receipt_id'],receipt['deletion_capability']))
        self.assertGreaterEqual(self.admin.execute('SELECT ops.apply_deletion_ledger()').fetchone()[0],1)
        self.assertEqual(self.admin.execute('SELECT count(*) FROM identity.accounts WHERE id=%s',(self.tenant[0],)).fetchone()[0],0)


if __name__=='__main__': unittest.main(verbosity=2)
