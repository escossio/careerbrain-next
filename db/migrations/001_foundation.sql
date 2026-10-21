-- Objects are owned by a NOLOGIN owner; runtimes never inherit ownership.
CREATE SCHEMA identity;
CREATE SCHEMA catalog;
CREATE SCHEMA private;
CREATE SCHEMA queue;
REVOKE ALL ON SCHEMA identity, catalog, private, queue FROM PUBLIC;
ALTER DEFAULT PRIVILEGES REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

CREATE TABLE identity.accounts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  account_created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
  state text NOT NULL DEFAULT 'ACTIVE' CHECK (state IN ('ACTIVE','DELETING')),
  deletion_epoch bigint NOT NULL DEFAULT 0 CHECK (deletion_epoch >= 0),
  profile_generation bigint NOT NULL DEFAULT 0 CHECK (profile_generation >= 0)
);
CREATE TABLE private.tenants (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id uuid NOT NULL UNIQUE REFERENCES identity.accounts ON DELETE CASCADE
);
CREATE TABLE identity.external_identities (
  issuer text NOT NULL CHECK (issuer = 'https://accounts.google.com'),
  subject text NOT NULL CHECK (length(subject) BETWEEN 1 AND 255),
  account_id uuid NOT NULL REFERENCES identity.accounts ON DELETE CASCADE,
  PRIMARY KEY (issuer, subject)
);
CREATE FUNCTION identity.immutable_account() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.id IS DISTINCT FROM OLD.id OR NEW.account_created_at IS DISTINCT FROM OLD.account_created_at
     OR NEW.deletion_epoch < OLD.deletion_epoch OR NEW.profile_generation < OLD.profile_generation THEN
    RAISE EXCEPTION 'immutable account identity or monotonic field' USING ERRCODE='23514';
  END IF;
  IF OLD.state='DELETING' AND NEW.state<>'DELETING' THEN
    RAISE EXCEPTION 'deletion cannot be undone' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER immutable_account BEFORE UPDATE ON identity.accounts
FOR EACH ROW EXECUTE FUNCTION identity.immutable_account();

CREATE FUNCTION identity.active_tenant() RETURNS uuid
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE tenant uuid;
BEGIN
  BEGIN tenant := nullif(current_setting('careerbrain.tenant_id', true),'')::uuid;
  EXCEPTION WHEN invalid_text_representation THEN RETURN NULL; END;
  RETURN (SELECT t.id FROM private.tenants t JOIN identity.accounts a ON a.id=t.account_id
          WHERE t.id=tenant AND a.state='ACTIVE');
END $$;
CREATE FUNCTION identity.provision(canonical_issuer text, stable_subject text)
RETURNS TABLE(user_id uuid, tenant_id uuid, account_created_at timestamptz, state text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE account uuid;
BEGIN
  IF canonical_issuer IS DISTINCT FROM 'https://accounts.google.com'
     OR stable_subject IS NULL OR length(stable_subject) NOT BETWEEN 1 AND 255 THEN
    RAISE EXCEPTION 'invalid identity' USING ERRCODE='22023';
  END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended(canonical_issuer || ':' || stable_subject,0));
  SELECT e.account_id INTO account FROM identity.external_identities e
    WHERE e.issuer=canonical_issuer AND e.subject=stable_subject;
  IF account IS NULL THEN
    INSERT INTO identity.accounts DEFAULT VALUES RETURNING id INTO account;
    INSERT INTO private.tenants(account_id) VALUES(account);
    INSERT INTO identity.external_identities VALUES(canonical_issuer,stable_subject,account);
  END IF;
  IF NOT EXISTS (SELECT FROM identity.accounts a WHERE a.id=account AND a.state='ACTIVE') THEN
    RAISE EXCEPTION 'account unavailable' USING ERRCODE='42501';
  END IF;
  RETURN QUERY SELECT a.id,t.id,a.account_created_at,a.state
    FROM identity.accounts a JOIN private.tenants t ON t.account_id=a.id WHERE a.id=account;
END $$;

CREATE TABLE catalog.sources (id uuid PRIMARY KEY, name text NOT NULL);
CREATE TABLE catalog.producers (id uuid PRIMARY KEY, active boolean NOT NULL DEFAULT true);
CREATE TABLE catalog.authorizations (
  id uuid PRIMARY KEY, producer_id uuid NOT NULL REFERENCES catalog.producers,
  source_id uuid NOT NULL REFERENCES catalog.sources, active boolean NOT NULL,
  UNIQUE(id,source_id)
);
CREATE TABLE catalog.evidence (
  id uuid PRIMARY KEY, source_id uuid NOT NULL REFERENCES catalog.sources,
  authorization_id uuid NOT NULL, digest text NOT NULL CHECK(digest ~ '^[a-f0-9]{64}$'),
  FOREIGN KEY(authorization_id,source_id) REFERENCES catalog.authorizations(id,source_id),
  UNIQUE(id,source_id)
);
CREATE TABLE catalog.vacancies (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), source_id uuid NOT NULL REFERENCES catalog.sources,
  source_vacancy_id text NOT NULL, content jsonb NOT NULL CHECK(jsonb_typeof(content)='object'),
  content_version bigint NOT NULL DEFAULT 1 CHECK(content_version>0),
  UNIQUE(source_id,source_vacancy_id), UNIQUE(id,source_id)
);
CREATE TABLE catalog.publication_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), vacancy_id uuid NOT NULL,
  source_id uuid NOT NULL, source_event_id text NOT NULL,
  kind text NOT NULL CHECK(kind IN ('original','republication')),
  predecessor_id uuid REFERENCES catalog.publication_events,
  published_at timestamptz NOT NULL, observed_at timestamptz NOT NULL,
  received_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
  evidence_id uuid NOT NULL, state text NOT NULL DEFAULT 'ACTIVE' CHECK(state IN ('ACTIVE','CLOSED','WITHDRAWN')),
  FOREIGN KEY(vacancy_id,source_id) REFERENCES catalog.vacancies(id,source_id),
  FOREIGN KEY(evidence_id,source_id) REFERENCES catalog.evidence(id,source_id),
  UNIQUE(source_id,source_event_id),
  CHECK(published_at<=observed_at AND observed_at<=received_at),
  CHECK((kind='original' AND predecessor_id IS NULL) OR (kind='republication' AND predecessor_id IS NOT NULL))
);
CREATE FUNCTION catalog.guard_event() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
  IF TG_OP='INSERT' THEN NEW.received_at := transaction_timestamp(); END IF;
  IF TG_OP='UPDATE' THEN
    IF ROW(NEW.id,NEW.vacancy_id,NEW.source_id,NEW.source_event_id,NEW.kind,NEW.predecessor_id,NEW.published_at,NEW.observed_at,NEW.received_at,NEW.evidence_id)
       IS DISTINCT FROM ROW(OLD.id,OLD.vacancy_id,OLD.source_id,OLD.source_event_id,OLD.kind,OLD.predecessor_id,OLD.published_at,OLD.observed_at,OLD.received_at,OLD.evidence_id) THEN
      RAISE EXCEPTION 'immutable publication event' USING ERRCODE='23514';
    END IF;
    IF OLD.state<>'ACTIVE' AND NEW.state<>OLD.state THEN
      RAISE EXCEPTION 'event cannot be reopened' USING ERRCODE='23514';
    END IF;
  ELSIF NEW.kind='republication' AND NOT EXISTS (
    SELECT FROM catalog.publication_events p WHERE p.id=NEW.predecessor_id
      AND p.vacancy_id=NEW.vacancy_id AND p.published_at<NEW.published_at AND p.evidence_id<>NEW.evidence_id
  ) THEN RAISE EXCEPTION 'unproven republication' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_event BEFORE INSERT OR UPDATE ON catalog.publication_events
FOR EACH ROW EXECUTE FUNCTION catalog.guard_event();
CREATE TABLE catalog.revisions (
  source_id uuid NOT NULL REFERENCES catalog.sources, revision_id text NOT NULL,
  event_id uuid NOT NULL REFERENCES catalog.publication_events,
  digest text NOT NULL CHECK(digest ~ '^[a-f0-9]{64}$'), PRIMARY KEY(source_id,revision_id)
);
CREATE TABLE catalog.semantic_results (
  event_id uuid REFERENCES catalog.publication_events, extractor_version text NOT NULL,
  taxonomy_version text NOT NULL, input_digest text NOT NULL CHECK(input_digest ~ '^[a-f0-9]{64}$'),
  result jsonb NOT NULL, PRIMARY KEY(event_id,extractor_version,taxonomy_version,input_digest)
);
CREATE TABLE ops.ingestion_receipts (
  producer_id uuid REFERENCES catalog.producers, route_version text NOT NULL,
  batch_id text NOT NULL CHECK(length(batch_id) BETWEEN 1 AND 128),
  digest text NOT NULL CHECK(digest ~ '^[a-f0-9]{64}$'), state text NOT NULL CHECK(state IN ('PENDING','ACCEPTED','REJECTED')),
  receipt jsonb, created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
  PRIMARY KEY(producer_id,route_version,batch_id)
);
CREATE TABLE queue.catalog_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), event_id uuid NOT NULL REFERENCES catalog.publication_events,
  task_version text NOT NULL, state text NOT NULL DEFAULT 'READY' CHECK(state IN ('READY','LEASED','DONE','FAILED')),
  created_at timestamptz NOT NULL DEFAULT transaction_timestamp(), available_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
  attempts integer NOT NULL DEFAULT 0 CHECK(attempts>=0), lease_until timestamptz,
  lease_owner uuid, fencing_token bigint NOT NULL DEFAULT 0 CHECK(fencing_token>=0),
  UNIQUE(event_id,task_version), CHECK((state='LEASED')=(lease_until IS NOT NULL AND lease_owner IS NOT NULL))
);
CREATE TABLE queue.catalog_outbox (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, event_id uuid NOT NULL REFERENCES catalog.publication_events,
  event_version text NOT NULL, kind text NOT NULL CHECK(kind IN ('PUBLISHED','CORRECTED','REMOVED')),
  created_at timestamptz NOT NULL DEFAULT transaction_timestamp(), delivered_at timestamptz,
  UNIQUE(event_id,event_version,kind)
);

CREATE TABLE private.profiles (
  tenant_id uuid PRIMARY KEY REFERENCES private.tenants ON DELETE CASCADE,
  profile_version bigint NOT NULL CHECK(profile_version>0), generation bigint NOT NULL CHECK(generation>=0),
  deletion_epoch bigint NOT NULL CHECK(deletion_epoch>=0), attributes jsonb NOT NULL CHECK(jsonb_typeof(attributes)='array'),
  extractor_version text NOT NULL, taxonomy_version text NOT NULL
);
CREATE FUNCTION private.guard_profile() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
  IF NOT EXISTS (SELECT FROM private.tenants t JOIN identity.accounts a ON a.id=t.account_id
      WHERE t.id=NEW.tenant_id AND a.state='ACTIVE' AND a.profile_generation=NEW.generation AND a.deletion_epoch=NEW.deletion_epoch)
     OR (TG_OP='UPDATE' AND NEW.profile_version<=OLD.profile_version) THEN
    RAISE EXCEPTION 'stale private result' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_profile BEFORE INSERT OR UPDATE ON private.profiles
FOR EACH ROW EXECUTE FUNCTION private.guard_profile();
CREATE TABLE private.applications (
  tenant_id uuid REFERENCES private.tenants ON DELETE CASCADE,
  event_id uuid REFERENCES catalog.publication_events,
  state text NOT NULL CHECK(state IN ('SAVED','APPLIED','INTERVIEW','OFFER','REJECTED','WITHDRAWN')),
  version bigint NOT NULL DEFAULT 1 CHECK(version>0), request_id text NOT NULL,
  PRIMARY KEY(tenant_id,event_id), UNIQUE(tenant_id,request_id)
);
CREATE TABLE private.recommendations (
  tenant_id uuid REFERENCES private.tenants ON DELETE CASCADE, event_id uuid REFERENCES catalog.publication_events,
  profile_version bigint NOT NULL CHECK(profile_version>0), policy_version text NOT NULL,
  affinity numeric NOT NULL CHECK(affinity BETWEEN 0 AND 1), PRIMARY KEY(tenant_id,event_id)
);
CREATE FUNCTION private.event_eligible(tenant uuid,event uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT EXISTS(SELECT FROM private.tenants t JOIN identity.accounts a ON a.id=t.account_id,
   catalog.publication_events e WHERE t.id=tenant AND e.id=event AND a.state='ACTIVE'
   AND e.state='ACTIVE' AND e.published_at>=a.account_created_at)
$$;
CREATE FUNCTION private.guard_recommendation() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
  IF NOT private.event_eligible(NEW.tenant_id,NEW.event_id) THEN
    RAISE EXCEPTION 'ineligible publication' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_recommendation BEFORE INSERT OR UPDATE ON private.recommendations
FOR EACH ROW EXECUTE FUNCTION private.guard_recommendation();
CREATE TABLE private.feed_counters (
  tenant_id uuid PRIMARY KEY REFERENCES private.tenants ON DELETE CASCADE, sequence bigint NOT NULL DEFAULT 0
);
CREATE TABLE private.feed (
  tenant_id uuid REFERENCES private.tenants ON DELETE CASCADE, sequence bigint NOT NULL,
  event_id uuid REFERENCES catalog.publication_events, kind text NOT NULL CHECK(kind IN ('UPSERT','REMOVED')),
  created_at timestamptz NOT NULL DEFAULT transaction_timestamp(), PRIMARY KEY(tenant_id,sequence)
);
CREATE FUNCTION private.feed_sequence() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
  IF NEW.tenant_id IS DISTINCT FROM identity.active_tenant() THEN
    RAISE EXCEPTION 'tenant denied' USING ERRCODE='42501';
  END IF;
  INSERT INTO private.feed_counters(tenant_id,sequence) VALUES(NEW.tenant_id,1)
    ON CONFLICT(tenant_id) DO UPDATE SET sequence=private.feed_counters.sequence+1 RETURNING sequence INTO NEW.sequence;
  RETURN NEW;
END $$;
CREATE TRIGGER feed_sequence BEFORE INSERT ON private.feed FOR EACH ROW EXECUTE FUNCTION private.feed_sequence();
CREATE TABLE private.commands (
  tenant_id uuid REFERENCES private.tenants ON DELETE CASCADE, route text NOT NULL, request_id text NOT NULL,
  digest text NOT NULL CHECK(digest ~ '^[a-f0-9]{64}$'), response jsonb NOT NULL,
  PRIMARY KEY(tenant_id,route,request_id)
);
CREATE TABLE queue.private_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES private.tenants ON DELETE CASCADE,
  kind text NOT NULL CHECK(kind IN ('RESUME','MATCH')),
  temporary_handle uuid, generation bigint NOT NULL CHECK(generation>=0), deletion_epoch bigint NOT NULL CHECK(deletion_epoch>=0),
  state text NOT NULL DEFAULT 'READY' CHECK(state IN ('READY','LEASED','DONE','FAILED','EXPIRED')),
  created_at timestamptz NOT NULL DEFAULT transaction_timestamp(), expires_at timestamptz NOT NULL,
  attempts integer NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 3), fencing_token bigint NOT NULL DEFAULT 0,
  lease_owner uuid, lease_until timestamptz,
  CHECK(expires_at>created_at AND expires_at<=created_at+interval '15 minutes'),
  CHECK(kind<>'RESUME' OR temporary_handle IS NOT NULL),
  CHECK((state='LEASED')=(lease_owner IS NOT NULL AND lease_until IS NOT NULL))
);
CREATE TABLE ops.deletion_ledger (
  account_id uuid PRIMARY KEY, deletion_epoch bigint NOT NULL CHECK(deletion_epoch>0),
  requested_at timestamptz NOT NULL DEFAULT transaction_timestamp(), expires_at timestamptz NOT NULL,
  CHECK(expires_at>requested_at AND expires_at<=requested_at+interval '30 days')
);
CREATE TABLE ops.audit_events (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, action text NOT NULL,
  entity_id uuid, created_at timestamptz NOT NULL DEFAULT transaction_timestamp(), actor_role text NOT NULL
);
CREATE FUNCTION ops.begin_deletion() RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE account uuid; epoch bigint;
BEGIN
  SELECT t.account_id INTO account FROM private.tenants t WHERE t.id=identity.active_tenant();
  IF account IS NULL THEN RAISE EXCEPTION 'tenant denied' USING ERRCODE='42501'; END IF;
  UPDATE identity.accounts SET state='DELETING',deletion_epoch=deletion_epoch+1 WHERE id=account RETURNING deletion_epoch INTO epoch;
  INSERT INTO ops.deletion_ledger(account_id,deletion_epoch,expires_at) VALUES(account,epoch,transaction_timestamp()+interval '30 days')
    ON CONFLICT(account_id) DO NOTHING;
  INSERT INTO ops.audit_events(action,entity_id,actor_role) VALUES('DELETION_REQUESTED',account,session_user);
END $$;
CREATE FUNCTION ops.apply_deletion_ledger() RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE removed bigint;
BEGIN
  -- Only a separately supplied, verified ledger may be applied before restore release.
  DELETE FROM identity.accounts a USING ops.deletion_ledger l WHERE a.id=l.account_id;
  GET DIAGNOSTICS removed=ROW_COUNT;
  RETURN removed;
END $$;

-- FORCE RLS and explicit owner-only policy also apply inside trusted definers.
DO $$ DECLARE t regclass; BEGIN
  FOREACH t IN ARRAY ARRAY['identity.accounts'::regclass,'identity.external_identities'::regclass,
    'private.tenants'::regclass,'private.profiles'::regclass,'private.applications'::regclass,
    'private.recommendations'::regclass,'private.feed_counters'::regclass,'private.feed'::regclass,
    'private.commands'::regclass,'queue.private_jobs'::regclass] LOOP
    EXECUTE format('ALTER TABLE %s ENABLE ROW LEVEL SECURITY',t);
    EXECUTE format('ALTER TABLE %s FORCE ROW LEVEL SECURITY',t);
    EXECUTE format('CREATE POLICY owner_internal ON %s TO cb_owner USING(true) WITH CHECK(true)',t);
  END LOOP;
  FOREACH t IN ARRAY ARRAY['private.tenants'::regclass,'private.profiles'::regclass,'private.applications'::regclass,
    'private.recommendations'::regclass,'private.feed_counters'::regclass,'private.feed'::regclass,
    'private.commands'::regclass,'queue.private_jobs'::regclass] LOOP
    EXECUTE format('CREATE POLICY tenant_scope ON %s TO cb_api,cb_private_worker USING(%I=identity.active_tenant()) WITH CHECK(%I=identity.active_tenant())',t,
      CASE WHEN t='private.tenants'::regclass THEN 'id' ELSE 'tenant_id' END,
      CASE WHEN t='private.tenants'::regclass THEN 'id' ELSE 'tenant_id' END);
  END LOOP;
END $$;
CREATE POLICY recommendation_visibility ON private.recommendations AS RESTRICTIVE TO cb_api,cb_private_worker
  USING(private.event_eligible(tenant_id,event_id));

GRANT USAGE ON SCHEMA identity TO cb_api,cb_private_worker,cb_auth;
GRANT USAGE ON SCHEMA catalog TO cb_api,cb_global_worker;
GRANT USAGE ON SCHEMA private,queue TO cb_api,cb_private_worker;
GRANT USAGE ON SCHEMA queue TO cb_global_worker;
GRANT USAGE ON SCHEMA ops TO cb_api,cb_privacy;
GRANT SELECT ON ALL TABLES IN SCHEMA catalog TO cb_api;
GRANT SELECT,INSERT,UPDATE ON ALL TABLES IN SCHEMA catalog TO cb_global_worker;
GRANT SELECT,INSERT,UPDATE,DELETE ON queue.catalog_jobs,queue.catalog_outbox TO cb_global_worker;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA queue TO cb_global_worker;
GRANT SELECT ON private.tenants,private.feed_counters TO cb_api,cb_private_worker;
GRANT SELECT,INSERT,UPDATE,DELETE ON private.profiles,private.applications,private.recommendations,private.feed,private.commands,queue.private_jobs TO cb_api,cb_private_worker;
GRANT INSERT ON ops.deletion_ledger TO cb_privacy;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA identity,private,ops,catalog FROM PUBLIC;
GRANT EXECUTE ON FUNCTION identity.active_tenant(),private.event_eligible(uuid,uuid) TO cb_api,cb_private_worker;
GRANT EXECUTE ON FUNCTION identity.provision(text,text) TO cb_auth;
GRANT EXECUTE ON FUNCTION ops.begin_deletion() TO cb_api;
GRANT EXECUTE ON FUNCTION ops.apply_deletion_ledger() TO cb_privacy;
