-- Producer credentials and approved source facts are provisioned out of band.
CREATE TABLE catalog.producer_tokens (
  token_digest text PRIMARY KEY CHECK (token_digest ~ '^[a-f0-9]{64}$'),
  producer_id uuid NOT NULL REFERENCES catalog.producers(id),
  scope text NOT NULL CHECK (scope = 'ingestion:write'),
  active boolean NOT NULL DEFAULT true
);
ALTER TABLE catalog.authorizations ADD COLUMN usage_allowed boolean NOT NULL DEFAULT false;
CREATE TABLE catalog.official_contacts (
  authorization_id uuid NOT NULL REFERENCES catalog.authorizations(id),
  kind text NOT NULL CHECK (kind IN ('https','email')),
  value text NOT NULL,
  PRIMARY KEY (authorization_id,kind,value)
);
ALTER TABLE catalog.evidence
  ADD COLUMN kind text CHECK (kind IN ('source_api','source_statement','source_signed_record')),
  ADD COLUMN url text,
  ADD COLUMN observed_at timestamptz,
  ADD COLUMN published_at timestamptz,
  ADD COLUMN source_event_id text,
  ADD COLUMN extractor_version text;
CREATE TABLE catalog.ingestion_events (
  event_id uuid PRIMARY KEY REFERENCES catalog.publication_events(id),
  record_digest text NOT NULL CHECK (record_digest ~ '^[a-f0-9]{64}$')
);
CREATE FUNCTION catalog.authenticate_producer(candidate_digest text) RETURNS uuid
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT t.producer_id FROM catalog.producer_tokens t JOIN catalog.producers p ON p.id=t.producer_id
 WHERE t.token_digest=candidate_digest AND t.active AND p.active AND t.scope='ingestion:write'
$$;
REVOKE ALL ON catalog.producer_tokens,catalog.official_contacts,catalog.ingestion_events FROM PUBLIC;
REVOKE ALL ON FUNCTION catalog.authenticate_producer(text) FROM PUBLIC;
GRANT USAGE ON SCHEMA catalog,queue,ops TO cb_ingest;
GRANT EXECUTE ON FUNCTION catalog.authenticate_producer(text) TO cb_ingest;
GRANT SELECT ON catalog.sources,catalog.producers,catalog.authorizations,catalog.evidence,
  catalog.official_contacts,catalog.vacancies,catalog.publication_events,catalog.revisions,
  catalog.ingestion_events TO cb_ingest;
GRANT INSERT ON catalog.vacancies,catalog.publication_events,catalog.revisions,
  catalog.ingestion_events TO cb_ingest;
GRANT UPDATE(content,content_version) ON catalog.vacancies TO cb_ingest;
GRANT UPDATE(state) ON catalog.publication_events TO cb_ingest;
GRANT SELECT,INSERT,UPDATE ON ops.ingestion_receipts TO cb_ingest;
GRANT SELECT,INSERT ON queue.catalog_jobs,queue.catalog_outbox TO cb_ingest;
GRANT USAGE ON SEQUENCE queue.catalog_outbox_id_seq TO cb_ingest;
