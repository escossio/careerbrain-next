-- Execution 05: additive classifier state; legacy semantic_results remains readable.
ALTER TABLE queue.catalog_jobs
  ADD COLUMN content_version bigint CHECK (content_version > 0),
  ADD COLUMN content_digest text CHECK (content_digest ~ '^[a-f0-9]{64}$'),
  ADD COLUMN taxonomy_version text,
  ADD COLUMN model_version text,
  ADD COLUMN prompt_version text,
  ADD COLUMN last_error_code text;
CREATE INDEX catalog_job_expired_lease ON queue.catalog_jobs(lease_until,id)
  WHERE state='LEASED';
CREATE INDEX catalog_job_aging ON queue.catalog_jobs(created_at,id)
  WHERE state='READY';

CREATE TABLE catalog.classification_cache (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  vacancy_id uuid NOT NULL REFERENCES catalog.vacancies(id),
  content_version bigint NOT NULL CHECK(content_version > 0),
  content_digest text NOT NULL CHECK(content_digest ~ '^[a-f0-9]{64}$'),
  taxonomy_version text NOT NULL,
  model_version text NOT NULL,
  prompt_version text NOT NULL,
  status text NOT NULL CHECK(status IN ('READY','UNCERTAIN')),
  result jsonb NOT NULL CHECK(jsonb_typeof(result)='object'),
  created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
  UNIQUE(vacancy_id,content_version,content_digest,taxonomy_version,model_version,prompt_version)
);
CREATE TABLE catalog.event_classifications (
  event_id uuid PRIMARY KEY REFERENCES catalog.publication_events(id),
  cache_id uuid NOT NULL REFERENCES catalog.classification_cache(id),
  updated_at timestamptz NOT NULL DEFAULT transaction_timestamp()
);
CREATE TABLE ops.classifier_policy (
  singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
  taxonomy_version text NOT NULL,
  model_version text NOT NULL,
  prompt_version text NOT NULL,
  changed_at timestamptz NOT NULL DEFAULT transaction_timestamp()
);
CREATE VIEW catalog.current_classifications AS
  SELECT p.event_id,p.cache_id,c.result,c.status,c.content_version,
    c.taxonomy_version,c.model_version,c.prompt_version
  FROM catalog.event_classifications p
  JOIN catalog.classification_cache c ON c.id=p.cache_id
  JOIN catalog.publication_events e ON e.id=p.event_id
  JOIN catalog.vacancies v ON v.id=e.vacancy_id
  JOIN ops.classifier_policy policy ON policy.singleton
  WHERE e.state='ACTIVE' AND c.vacancy_id=v.id AND c.content_version=v.content_version
    AND c.taxonomy_version=policy.taxonomy_version
    AND c.model_version=policy.model_version AND c.prompt_version=policy.prompt_version;

CREATE TABLE queue.classification_outbox (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  event_id uuid NOT NULL REFERENCES catalog.publication_events(id),
  cache_id uuid NOT NULL REFERENCES catalog.classification_cache(id),
  kind text NOT NULL CHECK(kind IN ('READY','UNCERTAIN')),
  created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
  delivered_at timestamptz,
  UNIQUE(event_id,cache_id)
);
CREATE INDEX classification_outbox_pending ON queue.classification_outbox(id)
  WHERE delivered_at IS NULL;
CREATE TABLE ops.classifier_gate (
  model_version text PRIMARY KEY,
  state text NOT NULL CHECK(state IN ('OPEN','BLOCKED')),
  reason text,
  updated_at timestamptz NOT NULL DEFAULT transaction_timestamp()
);

GRANT SELECT,INSERT,UPDATE ON catalog.classification_cache,catalog.event_classifications
  TO cb_global_worker;
GRANT SELECT ON catalog.current_classifications TO cb_api,cb_global_worker;
GRANT SELECT,INSERT,UPDATE ON queue.classification_outbox TO cb_global_worker;
GRANT USAGE ON SEQUENCE queue.classification_outbox_id_seq TO cb_global_worker;
GRANT USAGE ON SCHEMA ops TO cb_global_worker;
GRANT SELECT,INSERT,UPDATE ON ops.classifier_gate TO cb_global_worker;
GRANT SELECT,INSERT ON ops.classifier_policy TO cb_global_worker;
-- Row locks used for version fencing require UPDATE privilege; the worker may
-- touch only the immutable singleton key, never the active model versions.
GRANT UPDATE(singleton) ON ops.classifier_policy TO cb_global_worker;
