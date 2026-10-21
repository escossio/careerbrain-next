CREATE INDEX publication_eligibility ON catalog.publication_events(published_at DESC,id) WHERE state='ACTIVE';
CREATE INDEX account_state ON identity.accounts(state,id);
CREATE INDEX global_queue_ready ON queue.catalog_jobs(available_at,created_at DESC) WHERE state='READY';
CREATE INDEX global_outbox_pending ON queue.catalog_outbox(id) WHERE delivered_at IS NULL;
CREATE INDEX private_queue_ready ON queue.private_jobs(tenant_id,expires_at) WHERE state IN ('READY','LEASED');
CREATE INDEX ledger_expiry ON ops.deletion_ledger(expires_at);
