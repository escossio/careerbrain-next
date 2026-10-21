"""Project-owned SSH dispatcher: committed public source, isolated remote containers."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import tarfile
import uuid

ROOT=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--ssh-target',required=True)
    p.add_argument('--shared-lock',required=True)
    p.add_argument('--evidence-dir',type=Path,required=True)
    args=p.parse_args();os.umask(0o077);evidence=args.evidence_dir.resolve();evidence.mkdir(mode=0o700,parents=True,exist_ok=True)
    def git(*a):return subprocess.run(['git','--no-optional-locks','-C',str(ROOT),*a],capture_output=True,check=True).stdout
    if git('status','--porcelain=v1').strip():raise RuntimeError('Commit the reviewed source before dispatch')
    sha=git('rev-parse','HEAD').decode().strip()
    archive=evidence/'source.tar'
    with tarfile.open(archive,'w') as tar:
        for name in git('ls-files','-z').decode().strip('\0').split('\0'):
            path=ROOT/name
            if path.is_symlink() or not path.is_file():raise RuntimeError('Only regular tracked files may be dispatched')
            data=path.read_bytes();info=tarfile.TarInfo(name);info.size=len(data);info.mode=0o644;tar.addfile(info,io.BytesIO(data))
    job='/tmp/careerbrain-next-ci-'+uuid.uuid4().hex
    ssh=['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=8',args.ssh_target]
    def remote(command,**kwargs):return subprocess.run(ssh+[command],**kwargs)
    remote('mkdir -m 700 '+shlex.quote(job),capture_output=True,check=True)
    subprocess.run(['scp','-q','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',str(archive),args.ssh_target+':'+job+'/source.tar'],check=True)
    extract='''import pathlib,tarfile,sys
job=pathlib.Path(sys.argv[1]);code=job/'code';code.mkdir(mode=0o755)
with tarfile.open(job/'source.tar') as archive:
 for item in archive:
  relative=pathlib.PurePosixPath(item.name)
  assert item.isfile() and not relative.is_absolute() and '..' not in relative.parts
  target=code/pathlib.Path(relative);target.parent.mkdir(mode=0o755,parents=True,exist_ok=True)
  target.write_bytes(archive.extractfile(item).read());target.chmod(0o644)
(job/'source-sha').write_text(sys.argv[2]+'\\n')
'''
    remote('python3 -c '+shlex.quote(extract)+' '+shlex.quote(job)+' '+shlex.quote(sha),capture_output=True,check=True)
    record={'source_sha':sha,'source_archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'remote_job':job,'ssh_target':args.ssh_target,'shared_lock':args.shared_lock}
    (evidence/'dispatch.private.json').write_text(json.dumps(record,indent=2)+'\n')
    command='python3 '+shlex.quote(job+'/code/ci/worker_run.py')+' --job '+shlex.quote(job)+' --shared-lock '+shlex.quote(args.shared_lock)
    result=remote(command,capture_output=True)
    (evidence/'worker.stdout.log').write_bytes(result.stdout);(evidence/'worker.stderr.log').write_bytes(result.stderr)
    downloaded=subprocess.run(['scp','-q','-r','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',args.ssh_target+':'+job+'/results',str(evidence)],capture_output=True)
    if downloaded.returncode:raise RuntimeError('Could not recover worker evidence; remote job preserved')
    # Preserve remote evidence until explicitly cleaned; no shared prune or broad removal.
    print(json.dumps({'source_sha':sha,'exit_code':result.returncode,'evidence_dir':str(evidence)}))
    return result.returncode


if __name__=='__main__':raise SystemExit(main())
