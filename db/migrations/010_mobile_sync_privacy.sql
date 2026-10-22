-- Execution 08: tenant-scoped mobile projections, commands and erasure receipt.
ALTER TABLE private.recommendations
  ADD COLUMN available_at timestamptz NOT NULL DEFAULT transaction_timestamp();
CREATE INDEX recommendations_available ON private.recommendations(tenant_id,available_at,recommendation_id);

ALTER TABLE private.feed
  ADD COLUMN recommendation_id uuid,
  ADD COLUMN profile_version bigint;

CREATE TABLE private.feed_snapshots (
  cursor uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES private.tenants ON DELETE CASCADE,
  high_watermark bigint NOT NULL CHECK(high_watermark>=0), after_sequence bigint NOT NULL CHECK(after_sequence>=0),
  created_at timestamptz NOT NULL DEFAULT transaction_timestamp(), expires_at timestamptz NOT NULL DEFAULT transaction_timestamp()+interval '24 hours'
);
ALTER TABLE private.feed_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE private.feed_snapshots FORCE ROW LEVEL SECURITY;
CREATE POLICY owner_internal ON private.feed_snapshots TO cb_owner USING(true) WITH CHECK(true);
CREATE POLICY tenant_scope ON private.feed_snapshots TO cb_api USING(tenant_id=identity.active_tenant()) WITH CHECK(tenant_id=identity.active_tenant());

CREATE TABLE private.application_history (
  tenant_id uuid NOT NULL REFERENCES private.tenants ON DELETE CASCADE, event_id uuid NOT NULL REFERENCES catalog.publication_events,
  version bigint NOT NULL, state text NOT NULL CHECK(state IN ('SAVED','APPLIED','INTERVIEW','OFFER','REJECTED','WITHDRAWN')),
  request_id text NOT NULL, changed_at timestamptz NOT NULL DEFAULT transaction_timestamp(), PRIMARY KEY(tenant_id,event_id,version)
);
ALTER TABLE private.application_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE private.application_history FORCE ROW LEVEL SECURITY;
CREATE POLICY owner_internal ON private.application_history TO cb_owner USING(true) WITH CHECK(true);
CREATE POLICY tenant_scope ON private.application_history TO cb_api USING(tenant_id=identity.active_tenant()) WITH CHECK(tenant_id=identity.active_tenant());

CREATE TABLE ops.deletion_receipts (
  receipt_id uuid PRIMARY KEY, request_id text NOT NULL, capability_digest text NOT NULL UNIQUE,
  state text NOT NULL CHECK(state IN ('DELETING','ACTIVE_DATA_REMOVED','BACKUP_EXPIRY_PENDING','COMPLETE')),
  active_data_deadline timestamptz NOT NULL, backup_expiry_deadline timestamptz NOT NULL,
  expires_at timestamptz NOT NULL, UNIQUE(request_id,capability_digest)
);
ALTER TABLE ops.deletion_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops.deletion_receipts FORCE ROW LEVEL SECURITY;
CREATE POLICY owner_internal ON ops.deletion_receipts TO cb_owner USING(true) WITH CHECK(true);

CREATE OR REPLACE FUNCTION private.remove_match_projection(event uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE tenant uuid; removed uuid; recommendation uuid; version bigint;
BEGIN
  tenant:=identity.active_tenant(); IF tenant IS NULL THEN RAISE EXCEPTION 'tenant denied' USING ERRCODE='42501'; END IF;
  DELETE FROM private.recommendations WHERE tenant_id=tenant AND event_id=event
    RETURNING event_id,recommendation_id,profile_version INTO removed,recommendation,version;
  IF FOUND THEN
    INSERT INTO private.feed(tenant_id,sequence,event_id,kind,recommendation_id,profile_version)
      VALUES(tenant,0,removed,'REMOVED',recommendation,version);
    RETURN true;
  END IF;
  RETURN false;
END $$;

CREATE OR REPLACE FUNCTION private.complete_match_job(job uuid,owner uuid,fence bigint,result_affinity numeric,
  result_confidence numeric,result_reasons text[]) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE task queue.private_jobs%ROWTYPE; request private.match_requests%ROWTYPE; unchanged boolean; recommendation uuid;
BEGIN
  IF session_user<>'cb_private_worker' THEN RAISE EXCEPTION 'worker denied' USING ERRCODE='42501'; END IF;
  SELECT * INTO task FROM queue.private_jobs WHERE id=job AND kind='MATCH' AND state='LEASED' AND lease_owner=owner AND fencing_token=fence FOR UPDATE;
  IF NOT FOUND THEN RETURN 'FENCED'; END IF; SELECT * INTO request FROM private.match_requests WHERE job_id=job;
  IF task.expires_at<=transaction_timestamp() THEN UPDATE queue.private_jobs SET state='EXPIRED',lease_owner=NULL,lease_until=NULL WHERE id=job; RETURN 'EXPIRED'; END IF;
  IF NOT EXISTS(SELECT FROM private.tenants t JOIN identity.accounts a ON a.id=t.account_id JOIN private.profiles p ON p.tenant_id=t.id JOIN catalog.current_classifications c ON c.event_id=request.event_id JOIN ops.matching_policy policy ON policy.singleton WHERE t.id=task.tenant_id AND a.state='ACTIVE' AND a.profile_generation=task.generation AND a.deletion_epoch=task.deletion_epoch AND p.profile_version=request.profile_version AND p.generation=task.generation AND p.deletion_epoch=task.deletion_epoch AND c.cache_id=request.classification_cache_id AND policy.policy_version=request.policy_version AND private.event_eligible(t.id,request.event_id)) THEN UPDATE queue.private_jobs SET state='CANCELLED',lease_owner=NULL,lease_until=NULL WHERE id=job; RETURN 'CANCELLED'; END IF;
  IF (result_affinity IS NOT NULL AND result_affinity NOT BETWEEN 0 AND 1) OR (result_confidence IS NOT NULL AND result_confidence NOT BETWEEN 0 AND 1) OR cardinality(result_reasons) NOT BETWEEN 1 AND 20 OR NOT result_reasons <@ ARRAY['REQUIREMENT_UNKNOWN','EVIDENCED_AFFINITY']::text[] THEN RAISE EXCEPTION 'invalid match result' USING ERRCODE='22023'; END IF;
  SELECT r.event_id IS NOT NULL AND r.affinity IS NOT DISTINCT FROM result_affinity AND r.confidence IS NOT DISTINCT FROM result_confidence AND r.reasons=result_reasons INTO unchanged FROM private.recommendations r WHERE r.tenant_id=task.tenant_id AND r.event_id=request.event_id;
  INSERT INTO private.recommendations(tenant_id,event_id,profile_version,policy_version,affinity,classification_cache_id,generation,deletion_epoch,confidence,reasons) VALUES(task.tenant_id,request.event_id,request.profile_version,request.policy_version,result_affinity,request.classification_cache_id,task.generation,task.deletion_epoch,result_confidence,result_reasons)
  ON CONFLICT(tenant_id,event_id) DO UPDATE SET profile_version=EXCLUDED.profile_version,policy_version=EXCLUDED.policy_version,affinity=EXCLUDED.affinity,classification_cache_id=EXCLUDED.classification_cache_id,generation=EXCLUDED.generation,deletion_epoch=EXCLUDED.deletion_epoch,confidence=EXCLUDED.confidence,reasons=EXCLUDED.reasons
  RETURNING recommendation_id INTO recommendation;
  IF NOT COALESCE(unchanged,false) THEN PERFORM set_config('careerbrain.tenant_id',task.tenant_id::text,true); INSERT INTO private.feed(tenant_id,sequence,event_id,kind,recommendation_id,profile_version) VALUES(task.tenant_id,0,request.event_id,'UPSERT',recommendation,request.profile_version); END IF;
  UPDATE queue.private_jobs SET state='DONE',lease_owner=NULL,lease_until=NULL WHERE id=job; RETURN 'READY';
END $$;

CREATE FUNCTION private.apply_application(command jsonb, body_digest text) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE tenant uuid:=identity.active_tenant(); existing private.commands%ROWTYPE; current private.applications%ROWTYPE; event uuid; request text; expected bigint; next_state text;
BEGIN
  IF tenant IS NULL THEN RAISE EXCEPTION 'tenant denied' USING ERRCODE='42501'; END IF;
  request:=command->>'request_id'; event:=(command->>'publication_event_id')::uuid; expected:=(command->>'expected_version')::bigint; next_state:=command->>'state';
  SELECT * INTO existing FROM private.commands WHERE tenant_id=tenant AND route='applications' AND request_id=request FOR UPDATE;
  IF FOUND THEN IF existing.digest<>body_digest THEN RETURN 'IDEMPOTENCY_CONFLICT'; END IF; RETURN 'REPLAY'; END IF;
  SELECT * INTO current FROM private.applications WHERE tenant_id=tenant AND event_id=event FOR UPDATE;
  IF (NOT FOUND AND expected<>0) OR (FOUND AND current.version<>expected) THEN RETURN 'VERSION_CONFLICT'; END IF;
  IF FOUND THEN UPDATE private.applications SET state=next_state,version=current.version+1,request_id=request WHERE tenant_id=tenant AND event_id=event RETURNING * INTO current;
  ELSE INSERT INTO private.applications(tenant_id,event_id,state,version,request_id) VALUES(tenant,event,next_state,1,request) RETURNING * INTO current; END IF;
  INSERT INTO private.application_history VALUES(tenant,event,current.version,next_state,request);
  INSERT INTO private.commands(tenant_id,route,request_id,digest,response) VALUES(tenant,'applications',request,body_digest,jsonb_build_object('version',current.version));
  RETURN 'OK';
END $$;

CREATE FUNCTION private.ack_recommendations(request text, ids uuid[], body_digest text) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE tenant uuid:=identity.active_tenant(); existing private.commands%ROWTYPE;
BEGIN
  IF tenant IS NULL THEN RAISE EXCEPTION 'tenant denied' USING ERRCODE='42501'; END IF;
  SELECT * INTO existing FROM private.commands WHERE tenant_id=tenant AND route='recommendations/ack' AND request_id=request FOR UPDATE;
  IF FOUND THEN IF existing.digest<>body_digest THEN RETURN 'IDEMPOTENCY_CONFLICT'; END IF; RETURN 'REPLAY'; END IF;
  -- Read acknowledgement is deliberately monotonic/idempotent and never changes eligibility.
  INSERT INTO private.commands(tenant_id,route,request_id,digest,response) VALUES(tenant,'recommendations/ack',request,body_digest,'{}'); RETURN 'OK';
END $$;

CREATE FUNCTION ops.request_deletion(request text, capability_hash text) RETURNS TABLE(receipt_id uuid,active_deadline timestamptz,backup_deadline timestamptz)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE tenant uuid:=identity.active_tenant(); account uuid; epoch bigint; receipt uuid:=gen_random_uuid(); existing ops.deletion_receipts%ROWTYPE;
BEGIN
  IF tenant IS NULL OR request !~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$' THEN RAISE EXCEPTION 'tenant denied' USING ERRCODE='42501'; END IF;
  SELECT * INTO existing FROM ops.deletion_receipts WHERE request_id=request FOR UPDATE;
  IF FOUND THEN RETURN QUERY SELECT existing.receipt_id,existing.active_data_deadline,existing.backup_expiry_deadline; RETURN; END IF;
  SELECT account_id INTO account FROM private.tenants WHERE id=tenant FOR UPDATE; IF account IS NULL THEN RAISE EXCEPTION 'tenant denied' USING ERRCODE='42501'; END IF;
  UPDATE identity.accounts SET state='DELETING',deletion_epoch=deletion_epoch+1 WHERE id=account RETURNING deletion_epoch INTO epoch;
  INSERT INTO ops.deletion_ledger(account_id,deletion_epoch,expires_at) VALUES(account,epoch,transaction_timestamp()+interval '30 days') ON CONFLICT(account_id) DO UPDATE SET deletion_epoch=EXCLUDED.deletion_epoch;
  INSERT INTO ops.deletion_receipts VALUES(receipt,request,capability_hash,'ACTIVE_DATA_REMOVED',transaction_timestamp()+interval '24 hours',transaction_timestamp()+interval '30 days',transaction_timestamp()+interval '30 days');
  DELETE FROM private.tenants WHERE id=tenant;
  RETURN QUERY SELECT receipt,transaction_timestamp()+interval '24 hours',transaction_timestamp()+interval '30 days';
END $$;

CREATE FUNCTION ops.get_deletion_receipt(receipt uuid, capability_hash text)
RETURNS TABLE(request_id text,state text,active_data_deadline timestamptz,backup_expiry_deadline timestamptz)
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog AS $$ SELECT request_id,state,active_data_deadline,backup_expiry_deadline FROM ops.deletion_receipts WHERE receipt_id=receipt AND capability_digest=capability_hash AND expires_at>transaction_timestamp() $$;

GRANT SELECT,INSERT,DELETE ON private.feed_snapshots,private.application_history TO cb_api;
GRANT EXECUTE ON FUNCTION private.apply_application(jsonb,text),private.ack_recommendations(text,uuid[],text),ops.request_deletion(text,text),ops.get_deletion_receipt(uuid,text) TO cb_api;
