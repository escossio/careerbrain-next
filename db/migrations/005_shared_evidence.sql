-- Migration 005 belongs to execution 04: one proof may have several approved producers.
CREATE TABLE catalog.evidence_approvals (
  evidence_id uuid NOT NULL,
  source_id uuid NOT NULL,
  authorization_id uuid NOT NULL,
  PRIMARY KEY (evidence_id,authorization_id),
  FOREIGN KEY (evidence_id,source_id) REFERENCES catalog.evidence(id,source_id),
  FOREIGN KEY (authorization_id,source_id) REFERENCES catalog.authorizations(id,source_id)
);
INSERT INTO catalog.evidence_approvals(evidence_id,source_id,authorization_id)
  SELECT id,source_id,authorization_id FROM catalog.evidence;
ALTER TABLE catalog.ingestion_events ADD COLUMN content_digest text
  CHECK (content_digest IS NULL OR content_digest ~ '^[a-f0-9]{64}$');
GRANT SELECT ON catalog.evidence_approvals TO cb_ingest;
