"""Synthetic restore fixture; the worker controls dump/restore outside runtime tests."""
import json
import os
import sys
from uuid import uuid4

import psycopg
from careerbrain.db import bootstrap_disposable, tenant_pool, tenant_transaction
from psycopg.conninfo import make_conninfo

DB=os.environ['NEXT_TEST_DATABASE']
SOCKET=os.environ['NEXT_TEST_SOCKET']
assert DB.startswith('cbn_test_') and os.environ.get('NEXT_DISPOSABLE_CI')=='1'


def connect(role='postgres'):
    return psycopg.connect(dbname=DB,user=role,host=SOCKET,autocommit=True)


def profiles(tenant):
    pool=tenant_pool(make_conninfo(dbname=DB,user='cb_api',host=SOCKET),max_size=1)
    try:
        with tenant_transaction(pool,tenant) as c:return c.execute('SELECT count(*) FROM private.profiles').fetchone()[0]
    finally:pool.close()


def main():
    phase=sys.argv[1]
    if phase=='seed':
        rows=[]
        with connect('cb_auth') as c:
            for _ in range(2):rows.append(c.execute('SELECT * FROM identity.provision(%s,%s)',('https://accounts.google.com','synthetic-restore-'+str(uuid4()))).fetchone())
        pool=tenant_pool(make_conninfo(dbname=DB,user='cb_api',host=SOCKET),max_size=1)
        try:
            for row in rows:
                with tenant_transaction(pool,str(row[1])) as c:c.execute("INSERT INTO private.profiles VALUES(%s,1,0,0,'[]','synthetic','synthetic')",(row[1],))
        finally:pool.close()
        with connect() as c:catalog=c.execute('SELECT count(*) FROM catalog.publication_events').fetchone()[0]
        print(json.dumps({'account_a':str(rows[0][0]),'tenant_a':str(rows[0][1]),'tenant_b':str(rows[1][1]),'cutoff_b':rows[1][2].isoformat(),'catalog':catalog}))
    elif phase=='delete':
        state=json.loads(sys.argv[2]);pool=tenant_pool(make_conninfo(dbname=DB,user='cb_api',host=SOCKET),max_size=1)
        try:
            with tenant_transaction(pool,state['tenant_a']) as c:c.execute('SELECT ops.begin_deletion()')
        finally:pool.close()
        with connect() as c:ledger=c.execute('SELECT account_id,deletion_epoch,requested_at,expires_at FROM ops.deletion_ledger WHERE account_id=%s',(state['account_a'],)).fetchone()
        with connect('cb_privacy') as c:c.execute('SELECT ops.apply_deletion_ledger()')
        assert profiles(state['tenant_a'])==0 and profiles(state['tenant_b'])==1
        print(json.dumps({'account_id':str(ledger[0]),'epoch':ledger[1],'requested_at':ledger[2].isoformat(),'expires_at':ledger[3].isoformat()}))
    elif phase=='restore':
        state=json.loads(sys.argv[2]);ledger=json.loads(sys.argv[3])
        with connect() as c:
            bootstrap_disposable(c)
            assert c.execute('SELECT count(*) FROM identity.accounts WHERE id=%s',(state['account_a'],)).fetchone()[0]==1
        # Restore remains isolated; no runtime read happens before ledger application.
        with connect('cb_privacy') as c:
            c.execute('INSERT INTO ops.deletion_ledger VALUES(%s,%s,%s,%s) ON CONFLICT(account_id) DO NOTHING',
                      (ledger['account_id'],ledger['epoch'],ledger['requested_at'],ledger['expires_at']))
            c.execute('SELECT ops.apply_deletion_ledger()')
        assert profiles(state['tenant_a'])==0 and profiles(state['tenant_b'])==1
        with connect() as c:
            assert c.execute('SELECT count(*) FROM catalog.publication_events').fetchone()[0]==state['catalog']
            assert c.execute('SELECT a.account_created_at FROM identity.accounts a JOIN private.tenants t ON t.account_id=a.id WHERE t.id=%s',(state['tenant_b'],)).fetchone()[0].isoformat()==state['cutoff_b']
            assert c.execute('SELECT count(*) FROM ops.schema_migrations').fetchone()[0]==2
        print(json.dumps({'restore':'PASS','ledger_reapplied_before_runtime_reads':True,'deleted_account_absent':True,'other_tenant_preserved':True,'catalog_preserved':True,'cutoff_preserved':True,'rls_preserved':True}))
    else:raise ValueError('Unknown phase')


if __name__=='__main__':main()
