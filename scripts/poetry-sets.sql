-- Only user-selected runtime results are persisted; no anthology is shipped with the application.
CREATE TABLE IF NOT EXISTS poetry_sets (
  id VARCHAR(64) PRIMARY KEY,
  payload TEXT NOT NULL,
  created_at TIMESTAMP WITH TIME ZONE NOT NULL
);
