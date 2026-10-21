-- Reverting indexes is compatible with all rows and schema from migration 001.
DROP INDEX catalog.publication_eligibility;
DROP INDEX identity.account_state;
DROP INDEX queue.global_queue_ready;
DROP INDEX queue.global_outbox_pending;
DROP INDEX queue.private_queue_ready;
DROP INDEX ops.ledger_expiry;
