-- =============================================================================
-- ig_profile_scraper — Postgres tables for FileEnqueuer (mandatory for enqueue)
-- =============================================================================
--
-- HOW TO RUN (pick one)
--
--   psql "postgresql://USER:PASSWORD@HOST:PORT/DBNAME" -f scripts/postgres_setup.sql
--
--   Or from psql: \i scripts/postgres_setup.sql
--
-- ENV VARS (see src/igscraper/services/enqueue_client.py)
--   PUGSY_PG_HOST      default localhost
--   PUGSY_PG_PORT      default 5433
--   PUGSY_PG_USER      default postgres
--   PUGSY_PG_PASSWORD
--   PUGSY_PG_DATABASE  default postgres (local); override for production
--   Bootstrap writes ~/.slug/.env after successful setup.
--
-- ROW SEMANTICS
--   file_path: gs://bucket/path/file.jsonl when [main].push_to_gcs = 1, or an
--              absolute local filesystem path when push_to_gcs = 0.
--   thor_worker_id: must match [trace].thor_worker_id in config.toml (pipeline
--                     sets this on FileEnqueuer before INSERT).
--
-- =============================================================================

CREATE TABLE IF NOT EXISTS crawled_posts (
    id               SERIAL PRIMARY KEY,
    file_path        TEXT NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL,
    is_ingested      BOOLEAN NOT NULL DEFAULT FALSE,
    ingest_attempts  INTEGER NOT NULL DEFAULT 0,
    last_ingested_at TIMESTAMPTZ,
    last_error       TEXT,
    thor_worker_id   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS crawled_comments (
    id               SERIAL PRIMARY KEY,
    file_path        TEXT NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL,
    is_ingested      BOOLEAN NOT NULL DEFAULT FALSE,
    ingest_attempts  INTEGER NOT NULL DEFAULT 0,
    last_ingested_at TIMESTAMPTZ,
    last_error       TEXT,
    thor_worker_id   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_crawled_posts_worker ON crawled_posts (thor_worker_id);
CREATE INDEX IF NOT EXISTS idx_crawled_posts_ingested ON crawled_posts (is_ingested, created_at);
CREATE INDEX IF NOT EXISTS idx_crawled_comments_worker ON crawled_comments (thor_worker_id);
CREATE INDEX IF NOT EXISTS idx_crawled_comments_ingested ON crawled_comments (is_ingested, created_at);
