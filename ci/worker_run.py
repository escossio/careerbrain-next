"""Run only on an explicitly authorized worker, never the control plane."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

POSTGRES='postgres@sha256:3c5c8892d184f738f4fe282d14ddaa613a38f00f4189d2d94725ebe6f2909ddb'
PYTHON='python@sha256:cf50a4f6ac4f026458b08d5222023d700ac806410dff5e9ca8728fa44f2b850f'


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--job',type=Path,required=True)
    parser.add_argument('--shared-lock',type=Path,required=True)
    args=parser.parse_args();job=args.job.resolve();code=job/'code';results=job/'results'
    assert job.name.startswith('careerbrain-next-ci-') and code.is_dir()
    assert args.shared_lock.is_file()
    # Existing coordination lock is opened read-only: no shared configuration/script is changed.
    lock=args.shared_lock.open('rb');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    results.mkdir(mode=0o700,exist_ok=True)
    def run(*command,input=None,check=True):
        p=subprocess.run(command,cwd=code,input=input,capture_output=True)
        if check and p.returncode:
            sys.stdout.buffer.write(p.stdout);sys.stderr.buffer.write(p.stderr)
            raise RuntimeError(f'Command failed: {command[0]}, exit={p.returncode}')
        return p
    def inventory():
        ids=run('docker','ps','-aq','--no-trunc').stdout.decode().splitlines()
        if not ids:return []
        return sorted(run('docker','inspect','--format','{{.Id}} {{.Image}} {{.State.StartedAt}} {{.RestartCount}}',*ids).stdout.decode().splitlines())
    before=inventory();socket=job/'socket';socket.mkdir(mode=0o700);socket.chmod(0o1777)
    name='cbn-ci-'+uuid.uuid4().hex[:16];image='careerbrain-next-ci:'+hashlib.sha256((code/'requirements-db.txt').read_bytes()).hexdigest()[:16]
    report={'status':'FAIL','job_id':name,'source_sha':(job/'source-sha').read_text().strip(),'network':'none','postgres_image':POSTGRES,'python_image':PYTHON,'results':{}}
    started=False
    try:
        for base in [POSTGRES,PYTHON]:
            if run('docker','image','inspect',base,check=False).returncode:
                run('docker','pull',base)
        build=run('docker','build','--pull=false','--tag',image,'-f','ci/Dockerfile.database','.')
        (results/'build.log').write_bytes(build.stdout+build.stderr)
        started=True
        run('docker','run','--detach','--name',name,'--label','careerbrain-next.disposable=1',
            '--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges',
            '--pids-limit','128','--memory','256m','--memory-swap','256m','--ulimit','core=0',
            '--cpus','1','--user','70:70',
            '--tmpfs','/var/lib/postgresql/data:rw,nosuid,nodev,noexec,size=134217728,uid=70,gid=70,mode=0700',
            '--tmpfs','/tmp:rw,nosuid,nodev,noexec,size=33554432,mode=1777',
            '--mount',f'type=bind,src={socket},dst=/run/postgresql',
            '-e','POSTGRES_DB=cbn_test_suite','-e','POSTGRES_HOST_AUTH_METHOD=trust',POSTGRES,
            'postgres','-c','listen_addresses=','-c','unix_socket_directories=/run/postgresql',
            '-c','unix_socket_permissions=0777','-c','max_connections=20','-c','shared_buffers=32MB')
        started=True
        inspection=json.loads(run('docker','inspect',name).stdout)[0]
        safe={'network':inspection['HostConfig']['NetworkMode'],'privileged':inspection['HostConfig']['Privileged'],
              'cap_drop':inspection['HostConfig']['CapDrop'],'security_opt':inspection['HostConfig']['SecurityOpt'],
              'read_only':inspection['HostConfig']['ReadonlyRootfs'],'ports':inspection['HostConfig']['PortBindings'],
              'mounts':[{'type':m['Type'],'destination':m['Destination']} for m in inspection['Mounts']],
              'user':inspection['Config']['User']}
        assert safe['network']=='none' and safe['privileged'] is False and safe['read_only']
        assert 'ALL' in safe['cap_drop'] and not safe['ports'] and safe['user']=='70:70'
        assert all(m['destination'] in {'/run/postgresql','/var/lib/postgresql/data','/tmp'} and m['type']!='volume' for m in safe['mounts'])
        assert '/var/lib/postgresql/data' in inspection['HostConfig']['Tmpfs']
        (results/'isolation.json').write_text(json.dumps(safe,indent=2)+'\n')
        for _ in range(40):
            if run('docker','exec',name,'pg_isready','-h','/run/postgresql','-U','postgres','-d','cbn_test_suite',check=False).returncode==0:break
            time.sleep(.5)
        else:raise RuntimeError('Disposable PostgreSQL did not become ready')
        def client(command,database='cbn_test_suite'):
            p=run('docker','run','--rm','--network','none','--read-only','--cap-drop','ALL',
              '--security-opt','no-new-privileges','--pids-limit','128','--memory','256m','--memory-swap','256m',
              '--ulimit','core=0','--cpus','1',
              '--tmpfs','/tmp:rw,nosuid,nodev,noexec,size=33554432,mode=1777',
              '--mount',f'type=bind,src={code},dst=/workspace,readonly',
              '--mount',f'type=bind,src={socket},dst=/run/postgresql,readonly',
              '-e','NEXT_DISPOSABLE_CI=1','-e','NEXT_TEST_SOCKET=/run/postgresql',
              '-e','NEXT_TEST_DATABASE='+database,image,*command,check=False)
            return p
        cases=client(['python','-m','unittest','discover','-s','tests/integration','-p','database_cases.py','-v'])
        (results/'database.log').write_bytes(cases.stdout+cases.stderr)
        if cases.returncode:raise RuntimeError('PostgreSQL integration tests failed; see database.log')
        assert b'\nOK\n' in cases.stderr
        report['results']['database']='PASS'
        seed=client(['python','ci/restore_case.py','seed']);assert seed.returncode==0,seed.stderr.decode()
        state=json.loads(seed.stdout)
        dump=run('docker','exec',name,'pg_dump','-U','postgres','-d','cbn_test_suite','--format=custom').stdout
        (job/'backup.dump').write_bytes(dump);os.chmod(job/'backup.dump',0o600)
        removed=client(['python','ci/restore_case.py','delete',json.dumps(state)]);assert removed.returncode==0,removed.stderr.decode()
        ledger=json.loads(removed.stdout)
        run('docker','exec',name,'createdb','-U','postgres','-T','template0','cbn_test_restore')
        run('docker','exec','-i',name,'pg_restore','-U','postgres','-d','cbn_test_restore','--exit-on-error',input=dump)
        restored=client(['python','ci/restore_case.py','restore',json.dumps(state),json.dumps(ledger)],'cbn_test_restore')
        (results/'restore.log').write_bytes(restored.stdout+restored.stderr)
        if restored.returncode:raise RuntimeError('Restore/erasure verification failed; see restore.log')
        report['results']['restore']=json.loads(restored.stdout)
        authentication=client(['python','-m','unittest','discover','-s','tests/integration','-p','auth_cases.py','-v'])
        (results/'authentication.log').write_bytes(authentication.stdout+authentication.stderr)
        if authentication.returncode:raise RuntimeError('Identity integration tests failed; see authentication.log')
        assert b'\nOK\n' in authentication.stderr
        report['results']['authentication']='PASS'
        ingestion=client(['python','-m','unittest','discover','-s','tests/integration','-p','ingestion_cases.py','-v'])
        (results/'ingestion.log').write_bytes(ingestion.stdout+ingestion.stderr)
        if ingestion.returncode:raise RuntimeError('Ingestion integration tests failed; see ingestion.log')
        assert b'\nOK\n' in ingestion.stderr
        report['results']['ingestion']='PASS'
        classification=client(['python','-m','unittest','discover','-s','tests/integration',
                               '-p','classification_cases.py','-v'])
        (results/'classification.log').write_bytes(classification.stdout+classification.stderr)
        if classification.returncode:raise RuntimeError('Classification integration tests failed; see classification.log')
        assert b'\nOK\n' in classification.stderr
        report['results']['classification']='PASS'
        resume=client(['python','-m','unittest','discover','-s','tests/integration',
                       '-p','resume_cases.py','-v'])
        (results/'resume.log').write_bytes(resume.stdout+resume.stderr)
        if resume.returncode:raise RuntimeError('Resume integration tests failed; see resume.log')
        assert b'\nOK\n' in resume.stderr
        report['results']['resume']='PASS'
        matching=client(['python','-m','unittest','discover','-s','tests/integration',
                         '-p','matching_cases.py','-v'])
        (results/'matching.log').write_bytes(matching.stdout+matching.stderr)
        if matching.returncode:raise RuntimeError('PostgreSQL matching tests failed; see matching.log')
        assert b'\nOK\n' in matching.stderr
        report['results']['matching']='PASS'
        report['backup_sha256']=hashlib.sha256(dump).hexdigest()
        report['status']='PASS'
    except Exception as error:
        report['error']=str(error)
    finally:
        if started:
            logs=run('docker','logs',name,check=False);(results/'postgres.log').write_bytes(logs.stdout+logs.stderr)
            cleanup=run('docker','rm','-f','-v',name,check=False)
            report['postgres_container_removed']=cleanup.returncode==0
        report['existing_containers_preserved']=inventory()==before
        if not report['existing_containers_preserved']:report['status']='FAIL'
        report['result_hashes']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in results.iterdir() if p.is_file()}
        (results/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
        lock.close()
    return 0 if report['status']=='PASS' else 1


if __name__=='__main__':raise SystemExit(main())
