-- Execution 06: only opaque handles cross the durable queue boundary.
ALTER TABLE private.profiles
  ADD COLUMN status text NOT NULL DEFAULT 'READY' CHECK(status IN ('READY','UNCERTAIN'));
ALTER TABLE queue.private_jobs
  ADD COLUMN available_at timestamptz NOT NULL DEFAULT transaction_timestamp();
ALTER TABLE queue.private_jobs DROP CONSTRAINT queue_private_jobs_state_check;
ALTER TABLE queue.private_jobs ADD CONSTRAINT private_jobs_state_check
  CHECK(state IN ('READY','LEASED','DONE','FAILED','EXPIRED','CANCELLED'));
CREATE INDEX private_resume_ready ON queue.private_jobs(expires_at,available_at,id)
  WHERE kind='RESUME' AND state IN ('READY','LEASED');

CREATE TABLE private.resume_requests (
  tenant_id uuid NOT NULL REFERENCES private.tenants ON DELETE CASCADE,
  request_id text NOT NULL CHECK(request_id ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$'),
  job_id uuid NOT NULL UNIQUE REFERENCES queue.private_jobs ON DELETE CASCADE,
  generation bigint NOT NULL CHECK(generation>0),
  deletion_epoch bigint NOT NULL CHECK(deletion_epoch>=0),
  expires_at timestamptz NOT NULL,
  PRIMARY KEY(tenant_id,request_id)
);
ALTER TABLE private.resume_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE private.resume_requests FORCE ROW LEVEL SECURITY;
CREATE POLICY owner_internal ON private.resume_requests TO cb_owner USING(true) WITH CHECK(true);
CREATE POLICY tenant_scope ON private.resume_requests TO cb_api,cb_private_worker
  USING(tenant_id=identity.active_tenant()) WITH CHECK(tenant_id=identity.active_tenant());

CREATE FUNCTION private.create_resume_job(request text, handle uuid)
RETURNS TABLE(job_id uuid,generation bigint,deletion_epoch bigint,expires_at timestamptz,replayed boolean)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE tenant uuid; account uuid; epoch bigint; next_generation bigint; existing private.resume_requests%ROWTYPE;
BEGIN
  IF request !~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$' OR handle IS NULL THEN
    RAISE EXCEPTION 'invalid resume request' USING ERRCODE='22023';
  END IF;
  SELECT t.id,t.account_id,a.deletion_epoch INTO tenant,account,epoch FROM private.tenants t
    JOIN identity.accounts a ON a.id=t.account_id
    WHERE t.id=identity.active_tenant() AND a.state='ACTIVE' FOR UPDATE OF a;
  IF tenant IS NULL THEN RAISE EXCEPTION 'tenant denied' USING ERRCODE='42501'; END IF;
  SELECT * INTO existing FROM private.resume_requests WHERE tenant_id=tenant AND request_id=request FOR UPDATE;
  IF FOUND THEN
    RETURN QUERY SELECT existing.job_id,existing.generation,existing.deletion_epoch,existing.expires_at,true;
    RETURN;
  END IF;
  UPDATE identity.accounts SET profile_generation=profile_generation+1 WHERE id=account
    RETURNING profile_generation INTO next_generation;
  INSERT INTO queue.private_jobs(tenant_id,kind,temporary_handle,generation,deletion_epoch,expires_at)
    VALUES(tenant,'RESUME',handle,next_generation,epoch,transaction_timestamp()+interval '15 minutes')
    RETURNING id,queue.private_jobs.expires_at INTO job_id,expires_at;
  INSERT INTO private.resume_requests VALUES(tenant,request,job_id,next_generation,epoch,expires_at);
  replayed:=false;
  RETURN NEXT;
END $$;

CREATE FUNCTION private.claim_resume_job(owner uuid)
RETURNS TABLE(job_id uuid,tenant_id uuid,temporary_handle uuid,generation bigint,deletion_epoch bigint,
              expires_at timestamptz,fencing_token bigint)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
  IF owner IS NULL OR session_user<>'cb_private_worker' THEN RAISE EXCEPTION 'worker denied' USING ERRCODE='42501'; END IF;
  UPDATE queue.private_jobs SET state='EXPIRED',lease_owner=NULL,lease_until=NULL
    WHERE kind='RESUME' AND state IN ('READY','LEASED') AND expires_at<=transaction_timestamp();
  RETURN QUERY
  WITH candidate AS (
    SELECT id FROM queue.private_jobs WHERE kind='RESUME' AND state='READY'
      AND available_at<=transaction_timestamp() AND expires_at>transaction_timestamp()
      AND attempts<3 ORDER BY created_at,id FOR UPDATE SKIP LOCKED LIMIT 1
  ), claimed AS (
    UPDATE queue.private_jobs j SET state='LEASED',attempts=j.attempts+1,
      fencing_token=j.fencing_token+1,lease_owner=owner,
      lease_until=LEAST(j.expires_at,transaction_timestamp()+interval '30 seconds')
    FROM candidate WHERE j.id=candidate.id
    RETURNING j.id,j.tenant_id,j.temporary_handle,j.generation,j.deletion_epoch,j.expires_at,j.fencing_token
  ) SELECT * FROM claimed;
END $$;

CREATE FUNCTION private.expire_resume_job(job uuid, owner uuid, fence bigint) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
  IF session_user<>'cb_private_worker' THEN RAISE EXCEPTION 'worker denied' USING ERRCODE='42501'; END IF;
  UPDATE queue.private_jobs SET state='EXPIRED',lease_owner=NULL,lease_until=NULL
    WHERE id=job AND kind='RESUME' AND state='LEASED' AND lease_owner=owner AND fencing_token=fence;
  RETURN FOUND;
END $$;

CREATE FUNCTION private.fail_resume_job(job uuid, owner uuid, fence bigint, retryable boolean)
RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE attempt integer; expiry timestamptz;
BEGIN
  IF session_user<>'cb_private_worker' THEN RAISE EXCEPTION 'worker denied' USING ERRCODE='42501'; END IF;
  SELECT attempts,expires_at INTO attempt,expiry FROM queue.private_jobs
    WHERE id=job AND kind='RESUME' AND state='LEASED' AND lease_owner=owner AND fencing_token=fence FOR UPDATE;
  IF NOT FOUND THEN RETURN 'FENCED'; END IF;
  IF expiry<=transaction_timestamp() THEN
    UPDATE queue.private_jobs SET state='EXPIRED',lease_owner=NULL,lease_until=NULL WHERE id=job; RETURN 'EXPIRED';
  END IF;
  IF retryable AND attempt<3 THEN
    UPDATE queue.private_jobs SET state='READY',lease_owner=NULL,lease_until=NULL,
      available_at=LEAST(expires_at,transaction_timestamp()+(2^attempt * interval '1 second')) WHERE id=job;
    RETURN 'RETRY';
  END IF;
  UPDATE queue.private_jobs SET state='FAILED',lease_owner=NULL,lease_until=NULL WHERE id=job;
  RETURN 'FAILED';
END $$;

CREATE FUNCTION private.complete_resume_job(job uuid, owner uuid, fence bigint, result_status text,
  result_attributes jsonb, extractor text, taxonomy text) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE task queue.private_jobs%ROWTYPE; current_generation bigint; current_epoch bigint; profile_version bigint;
BEGIN
  IF session_user<>'cb_private_worker' THEN RAISE EXCEPTION 'worker denied' USING ERRCODE='42501'; END IF;
  SELECT * INTO task FROM queue.private_jobs WHERE id=job AND kind='RESUME' AND state='LEASED'
    AND lease_owner=owner AND fencing_token=fence FOR UPDATE;
  IF NOT FOUND THEN RETURN 'FENCED'; END IF;
  IF task.expires_at<=transaction_timestamp() THEN
    UPDATE queue.private_jobs SET state='EXPIRED',lease_owner=NULL,lease_until=NULL WHERE id=job; RETURN 'EXPIRED';
  END IF;
  SELECT a.profile_generation,a.deletion_epoch INTO current_generation,current_epoch FROM private.tenants t
    JOIN identity.accounts a ON a.id=t.account_id WHERE t.id=task.tenant_id AND a.state='ACTIVE' FOR UPDATE OF a;
  IF NOT FOUND OR current_generation<>task.generation OR current_epoch<>task.deletion_epoch THEN
    UPDATE queue.private_jobs SET state='CANCELLED',lease_owner=NULL,lease_until=NULL WHERE id=job; RETURN 'CANCELLED';
  END IF;
  IF result_status NOT IN ('READY','UNCERTAIN') OR jsonb_typeof(result_attributes)<>'array'
     OR jsonb_array_length(result_attributes)>200
     OR (result_status='READY' AND jsonb_array_length(result_attributes)=0)
     OR (result_status='UNCERTAIN' AND jsonb_array_length(result_attributes)<>0) THEN
    RAISE EXCEPTION 'invalid profile result' USING ERRCODE='22023';
  END IF;
  PERFORM set_config('careerbrain.tenant_id',task.tenant_id::text,true);
  INSERT INTO private.profiles(tenant_id,profile_version,generation,deletion_epoch,status,attributes,extractor_version,taxonomy_version)
    VALUES(task.tenant_id,1,task.generation,task.deletion_epoch,result_status,result_attributes,extractor,taxonomy)
  ON CONFLICT(tenant_id) DO UPDATE SET profile_version=private.profiles.profile_version+1,
    generation=EXCLUDED.generation,deletion_epoch=EXCLUDED.deletion_epoch,status=EXCLUDED.status,
    attributes=EXCLUDED.attributes,extractor_version=EXCLUDED.extractor_version,taxonomy_version=EXCLUDED.taxonomy_version
  RETURNING private.profiles.profile_version INTO profile_version;
  UPDATE queue.private_jobs SET state='DONE',lease_owner=NULL,lease_until=NULL WHERE id=job;
  RETURN result_status;
END $$;

CREATE FUNCTION private.cancel_resume_job(job uuid) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE handle uuid; account uuid;
BEGIN
  SELECT j.temporary_handle,t.account_id INTO handle,account FROM queue.private_jobs j JOIN private.tenants t ON t.id=j.tenant_id
    WHERE j.id=job AND j.kind='RESUME' AND j.tenant_id=identity.active_tenant()
      AND j.state IN ('READY','LEASED') FOR UPDATE OF j;
  IF NOT FOUND THEN RETURN NULL; END IF;
  UPDATE identity.accounts SET profile_generation=profile_generation+1 WHERE id=account;
  UPDATE queue.private_jobs SET state='CANCELLED',lease_owner=NULL,lease_until=NULL WHERE id=job;
  RETURN handle;
END $$;

CREATE FUNCTION private.resume_job_status(job uuid) RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
  SELECT CASE state WHEN 'READY' THEN 'PENDING' WHEN 'LEASED' THEN 'PROCESSING'
    WHEN 'DONE' THEN COALESCE((SELECT p.status FROM private.profiles p WHERE p.tenant_id=j.tenant_id),'READY')
    ELSE state END FROM queue.private_jobs j WHERE j.id=job AND j.kind='RESUME' AND j.tenant_id=identity.active_tenant()
$$;

CREATE FUNCTION private.reap_expired_resume_handles() RETURNS SETOF uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
  IF session_user<>'cb_private_worker' THEN RAISE EXCEPTION 'worker denied' USING ERRCODE='42501'; END IF;
  RETURN QUERY UPDATE queue.private_jobs SET state='EXPIRED',lease_owner=NULL,lease_until=NULL
    WHERE kind='RESUME' AND state IN ('READY','LEASED') AND expires_at<=transaction_timestamp()
    RETURNING temporary_handle;
END $$;

GRANT SELECT ON private.resume_requests TO cb_api,cb_private_worker;
GRANT EXECUTE ON FUNCTION private.create_resume_job(text,uuid),private.cancel_resume_job(uuid),
  private.resume_job_status(uuid) TO cb_api;
GRANT EXECUTE ON FUNCTION private.claim_resume_job(uuid),private.expire_resume_job(uuid,uuid,bigint),
  private.fail_resume_job(uuid,uuid,bigint,boolean),private.complete_resume_job(uuid,uuid,bigint,text,jsonb,text,text),
  private.reap_expired_resume_handles() TO cb_private_worker;
