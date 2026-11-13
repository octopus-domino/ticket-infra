-- Additive migration. Apply before starting a release using ddl-auto=validate.
CREATE TABLE IF NOT EXISTS journey_print_sources (
  id VARCHAR(64) PRIMARY KEY,
  source_json TEXT NOT NULL,
  updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
  version BIGINT
);
