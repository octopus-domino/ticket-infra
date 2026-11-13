-- Additive migration. Verification records do not contain the form's personal data.
CREATE TABLE IF NOT EXISTS workflow_visits (
  id VARCHAR(32) PRIMARY KEY,
  owner_id VARCHAR(120) NOT NULL,
  workflow_slug VARCHAR(48) NOT NULL,
  workflow_revision BIGINT NOT NULL,
  title VARCHAR(120) NOT NULL,
  issued_at TIMESTAMP WITH TIME ZONE NOT NULL,
  document_sha256 VARCHAR(64) NOT NULL,
  checked_at TIMESTAMP WITH TIME ZONE,
  visited_at TIMESTAMP WITH TIME ZONE,
  checked_by VARCHAR(120),
  note VARCHAR(500),
  version BIGINT
);
