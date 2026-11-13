-- Legacy releases remain manageable through their existing keys or ownership of every member.
ALTER TABLE journey_batches ADD COLUMN IF NOT EXISTS owner_id VARCHAR(36);
CREATE INDEX IF NOT EXISTS ix_journey_batch_owner ON journey_batches(owner_id, created_at);
