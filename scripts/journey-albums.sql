CREATE TABLE IF NOT EXISTS journey_albums (
  id VARCHAR(36) PRIMARY KEY,
  pictures TEXT NOT NULL,
  invitation_hash VARCHAR(64) NOT NULL,
  invitation_cipher TEXT NOT NULL,
  version BIGINT
);
