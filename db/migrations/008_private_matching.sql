-- Execution 07: versioned, tenant-scoped private matching.  No private payload
-- crosses the queue; the request key is enough to fence and recompute work.
ALTER TABLE private.recommendations
  ADD COLUMN recommendation_id uuid NOT NULL DEFAULT gen_random_uuid(),
  ADD COLUMN classification_cache_id uuid REFERENCES catalog.classification_cache(id),
  ADD COLUMN generation bigint CHECK(generation >= 0),
  ADD COLUMN deletion_epoch bigint CHECK(deletion_epoch >= 0),
  ADD COLUMN confidence numeric CHECK(confidence IS NULL OR confidence BETWEEN 0 AND 1),
  ADD COLUMN reasons text[] NOT NULL DEFAULT ARRAY[]::text[];
ALTER TABLE private.recommendations ALTER COLUMN affinity DROP NOT NULL;
ALTER TABLE private.recommendations
  ADD CONSTRAINT recommendation_reason_codes CHECK(
    classification_cache_id IS NULL OR (cardinality(reasons) BETWEEN 1 AND 20
    AND reasons <@ ARRAY['TEMPORAL_CUTOFF','REQUIREMENT_UNMET','REQUIREMENT_UNKNOWN',
                         'EVIDENCED_AFFINITY','SOURCE_WITHDRAWN','VACANCY_CLOSED']::text[])
  );
CREATE UNIQUE INDEX recommendations_public_id ON private.recommendations(recommendation_id);

CREATE TABLE ops.matching_policy (
  singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
  policy_version text NOT NULL CHECK(policy_version ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$'),
  changed_at timestamptz NOT NULL DEFAULT transaction_timestamp()
);
INSERT INTO ops.matching_policy(singleton,policy_version) VALUES(true,'matching-v1');

CREATE TABLE private.match_requests (
  tenant_id uuid NOT NULL REFERENCES private.tenants ON DELETE CASCADE,
  event_id uuid NOT NULL REFERENCES catalog.publication_events,
  profile_version bigint NOT NULL CHECK(profile_version > 0),
  classification_cache_id uuid NOT NULL REFERENCES catalog.classification_cache(id),
  policy_version text NOT NULL,
  job_id uuid NOT NULL UNIQUE REFERENCES queue.private_jobs ON DELETE CASCADE,
  PRIMARY KEY(tenant_id,event_id,profile_version,classification_cache_id,policy_version)
);
ALTER TABLE private.match_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE private.match_requests FORCE ROW LEVEL SECURITY;
CREATE POLICY owner_internal ON private.match_requests TO cb_owner USING(true) WITH CHECK(true);
CREATE POLICY tenant_scope ON private.match_requests TO cb_api,cb_private_worker
  USING(tenant_id=identity.active_tenant()) WITH CHECK(tenant_id=identity.active_tenant());

-- A view is the read boundary: old profile/policy/classification projections are
-- invisible immediately, even before their queued replacement is processed.
CREATE VIEW private.current_recommendations WITH (security_invoker=true) AS
  SELECT r.recommendation_id,r.tenant_id,r.event_id,r.profile_version,r.policy_version,
    r.affinity,r.confidence,r.reasons,r.classification_cache_id
  FROM private.recommendations r
  JOIN private.profiles p ON p.tenant_id=r.tenant_id
  JOIN private.match_requests q ON q.tenant_id=r.tenant_id AND q.event_id=r.event_id
    AND q.profile_version=r.profile_version AND q.classification_cache_id=r.classification_cache_id
    AND q.policy_version=r.policy_version
  JOIN catalog.current_classifications c ON c.event_id=r.event_id AND c.cache_id=r.classification_cache_id
  JOIN ops.matching_policy policy ON policy.singleton AND policy.policy_version=r.policy_version
  WHERE p.profile_version=r.profile_version AND private.event_eligible(r.tenant_id,r.event_id);

CREATE FUNCTION private.remove_match_projection(event uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE tenant uuid; removed uuid;
BEGIN
  tenant:=identity.active_tenant();
  IF tenant IS NULL THEN RAISE EXCEPTION 'tenant denied' USING ERRCODE='42501'; END IF;
  DELETE FROM private.recommendations WHERE tenant_id=tenant AND event_id=event RETURNING event_id INTO removed;
  IF FOUND THEN
    INSERT INTO private.feed(tenant_id,sequence,event_id,kind) VALUES(tenant,0,removed,'REMOVED');
    RETURN true;
  END IF;
  RETURN false;
END $$;

CREATE FUNCTION private.create_match_job(event uuid)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE tenant uuid; profile private.profiles%ROWTYPE; account identity.accounts%ROWTYPE;
  cache uuid; policy text; job uuid; prior uuid;
BEGIN
  tenant:=identity.active_tenant();
  IF tenant IS NULL THEN RAISE EXCEPTION 'tenant denied' USING ERRCODE='42501'; END IF;
  SELECT p.* INTO profile FROM private.profiles p WHERE p.tenant_id=tenant;
  SELECT a.* INTO account FROM private.tenants t JOIN identity.accounts a ON a.id=t.account_id WHERE t.id=tenant;
  IF NOT FOUND OR account.state<>'ACTIVE' OR profile.tenant_id IS NULL OR NOT private.event_eligible(tenant,event) THEN
    PERFORM private.remove_match_projection(event); RETURN NULL;
  END IF;
  SELECT c.cache_id INTO cache FROM catalog.current_classifications c WHERE c.event_id=event;
  SELECT p.policy_version INTO policy FROM ops.matching_policy p WHERE p.singleton;
  IF cache IS NULL OR policy IS NULL THEN RETURN NULL; END IF;
  SELECT job_id INTO prior FROM private.match_requests WHERE tenant_id=tenant AND event_id=event
    AND profile_version=profile.profile_version AND classification_cache_id=cache AND policy_version=policy;
  IF FOUND THEN RETURN prior; END IF;
  INSERT INTO queue.private_jobs(tenant_id,kind,generation,deletion_epoch,expires_at)
    VALUES(tenant,'MATCH',profile.generation,profile.deletion_epoch,transaction_timestamp()+interval '15 minutes') RETURNING id INTO job;
  INSERT INTO private.match_requests VALUES(tenant,event,profile.profile_version,cache,policy,job);
  RETURN job;
END $$;

CREATE FUNCTION private.claim_match_job(owner uuid)
RETURNS TABLE(job_id uuid,tenant_id uuid,event_id uuid,profile_version bigint,classification_cache_id uuid,
  policy_version text,generation bigint,deletion_epoch bigint,fencing_token bigint)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
  IF owner IS NULL OR session_user<>'cb_private_worker' THEN RAISE EXCEPTION 'worker denied' USING ERRCODE='42501'; END IF;
  UPDATE queue.private_jobs SET state='EXPIRED',lease_owner=NULL,lease_until=NULL
    WHERE kind='MATCH' AND state IN ('READY','LEASED') AND expires_at<=transaction_timestamp();
  RETURN QUERY WITH candidate AS (
    SELECT j.id FROM queue.private_jobs j WHERE j.kind='MATCH' AND j.state='READY'
      AND j.expires_at>transaction_timestamp() AND j.attempts<3 ORDER BY j.created_at,j.id FOR UPDATE SKIP LOCKED LIMIT 1
  ), claimed AS (
    UPDATE queue.private_jobs j SET state='LEASED',attempts=j.attempts+1,fencing_token=j.fencing_token+1,
      lease_owner=owner,lease_until=LEAST(j.expires_at,transaction_timestamp()+interval '30 seconds')
      FROM candidate WHERE j.id=candidate.id
      RETURNING j.id,j.tenant_id,j.generation,j.deletion_epoch,j.fencing_token
  ) SELECT c.id,c.tenant_id,r.event_id,r.profile_version,r.classification_cache_id,r.policy_version,
      c.generation,c.deletion_epoch,c.fencing_token FROM claimed c JOIN private.match_requests r ON r.job_id=c.id;
END $$;

CREATE FUNCTION private.complete_match_job(job uuid,owner uuid,fence bigint,result_affinity numeric,
  result_confidence numeric,result_reasons text[]) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE task queue.private_jobs%ROWTYPE; request private.match_requests%ROWTYPE; unchanged boolean;
BEGIN
  IF session_user<>'cb_private_worker' THEN RAISE EXCEPTION 'worker denied' USING ERRCODE='42501'; END IF;
  SELECT * INTO task FROM queue.private_jobs WHERE id=job AND kind='MATCH' AND state='LEASED'
    AND lease_owner=owner AND fencing_token=fence FOR UPDATE;
  IF NOT FOUND THEN RETURN 'FENCED'; END IF;
  SELECT * INTO request FROM private.match_requests WHERE job_id=job;
  IF task.expires_at<=transaction_timestamp() THEN
    UPDATE queue.private_jobs SET state='EXPIRED',lease_owner=NULL,lease_until=NULL WHERE id=job; RETURN 'EXPIRED';
  END IF;
  IF NOT EXISTS(SELECT FROM private.tenants t JOIN identity.accounts a ON a.id=t.account_id
      JOIN private.profiles p ON p.tenant_id=t.id JOIN catalog.current_classifications c ON c.event_id=request.event_id
      JOIN ops.matching_policy policy ON policy.singleton
      WHERE t.id=task.tenant_id AND a.state='ACTIVE' AND a.profile_generation=task.generation
       AND a.deletion_epoch=task.deletion_epoch AND p.profile_version=request.profile_version
       AND p.generation=task.generation AND p.deletion_epoch=task.deletion_epoch
       AND c.cache_id=request.classification_cache_id AND policy.policy_version=request.policy_version
       AND private.event_eligible(t.id,request.event_id)) THEN
    UPDATE queue.private_jobs SET state='CANCELLED',lease_owner=NULL,lease_until=NULL WHERE id=job; RETURN 'CANCELLED';
  END IF;
  IF (result_affinity IS NOT NULL AND result_affinity NOT BETWEEN 0 AND 1)
     OR (result_confidence IS NOT NULL AND result_confidence NOT BETWEEN 0 AND 1)
     OR cardinality(result_reasons) NOT BETWEEN 1 AND 20
     OR NOT result_reasons <@ ARRAY['REQUIREMENT_UNKNOWN','EVIDENCED_AFFINITY']::text[] THEN
    RAISE EXCEPTION 'invalid match result' USING ERRCODE='22023';
  END IF;
  SELECT r.event_id IS NOT NULL AND r.affinity IS NOT DISTINCT FROM result_affinity
    AND r.confidence IS NOT DISTINCT FROM result_confidence AND r.reasons=result_reasons
    INTO unchanged FROM private.recommendations r WHERE r.tenant_id=task.tenant_id AND r.event_id=request.event_id;
  INSERT INTO private.recommendations(tenant_id,event_id,profile_version,policy_version,affinity,classification_cache_id,
    generation,deletion_epoch,confidence,reasons) VALUES(task.tenant_id,request.event_id,request.profile_version,
    request.policy_version,result_affinity,request.classification_cache_id,task.generation,task.deletion_epoch,
    result_confidence,result_reasons)
  ON CONFLICT(tenant_id,event_id) DO UPDATE SET profile_version=EXCLUDED.profile_version,policy_version=EXCLUDED.policy_version,
    affinity=EXCLUDED.affinity,classification_cache_id=EXCLUDED.classification_cache_id,generation=EXCLUDED.generation,
    deletion_epoch=EXCLUDED.deletion_epoch,confidence=EXCLUDED.confidence,reasons=EXCLUDED.reasons;
  IF NOT COALESCE(unchanged,false) THEN
    PERFORM set_config('careerbrain.tenant_id',task.tenant_id::text,true);
    INSERT INTO private.feed(tenant_id,sequence,event_id,kind) VALUES(task.tenant_id,0,request.event_id,'UPSERT');
  END IF;
  UPDATE queue.private_jobs SET state='DONE',lease_owner=NULL,lease_until=NULL WHERE id=job; RETURN 'READY';
END $$;

GRANT SELECT ON ops.matching_policy TO cb_api,cb_private_worker;
GRANT SELECT ON catalog.current_classifications,catalog.classification_cache TO cb_private_worker;
GRANT SELECT ON private.match_requests,private.current_recommendations TO cb_api,cb_private_worker;
GRANT EXECUTE ON FUNCTION private.create_match_job(uuid),private.remove_match_projection(uuid) TO cb_private_worker;
GRANT EXECUTE ON FUNCTION private.claim_match_job(uuid),private.complete_match_job(uuid,uuid,bigint,numeric,numeric,text[]) TO cb_private_worker;
REVOKE INSERT,UPDATE,DELETE ON private.recommendations,private.feed FROM cb_api,cb_private_worker;
