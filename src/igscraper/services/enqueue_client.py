from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Optional

import psycopg
from dotenv import load_dotenv
from igscraper.logger import get_logger

logger = get_logger(__name__)
load_dotenv(dotenv_path=os.environ.get("ENV_FILE", ".env"), override=False)

def log_pg_env():
    logger.info(
        "Postgres env → host=%s port=%s db=%s user=%s",
        os.environ.get("PUGSY_PG_HOST"),
        os.environ.get("PUGSY_PG_PORT"),
        os.environ.get("PUGSY_PG_DATABASE"),
        os.environ.get("PUGSY_PG_USER"),
    )

log_pg_env()

@dataclass
class PostgresConfig:
    host: str
    port: int
    user: str
    password: str
    database: str

    @classmethod
    def from_env(cls) -> "PostgresConfig":
        return cls(
            host=os.environ.get("PUGSY_PG_HOST", "localhost"),
            port=int(os.environ.get("PUGSY_PG_PORT", "5433")),
            user=os.environ.get("PUGSY_PG_USER", "postgres"),
            password=os.environ.get("PUGSY_PG_PASSWORD", ""),
            database=os.environ.get("PUGSY_PG_DATABASE", ""),
        )

    def __repr__(self) -> str:
        """Safe string representation that redacts password."""
        return (
            f"PostgresConfig(host='{self.host}', port={self.port}, "
            f"user='{self.user}', password='***', database='{self.database}')"
        )

    def dsn(self) -> str:
        return (
            f"host={self.host} port={self.port} "
            f"dbname={self.database} user={self.user} password={self.password}"
        )



class FileEnqueuer:
    """
    Minimal client to insert a *file-based* ingestion job into Postgres.

    - kind="post"   -> inserts into crawled_posts
    - kind="comment"-> inserts into crawled_comments

    Schema assumed (includes thor_worker_id):

        CREATE TABLE crawled_posts (
            id              serial primary key,
            file_path       text not null,
            created_at      timestamptz not null,
            is_ingested     boolean not null default false,
            ingest_attempts int not null default 0,
            last_ingested_at timestamptz,
            last_error      text,
            thor_worker_id  text not null
        );

        -- same for crawled_comments
    """

    def __init__(self, pg_config: PostgresConfig) -> None:
        self._pg_config = pg_config
        self.thor_worker_id: str | None = None  # Set by backend after initialization
        logger.debug("[FileEnqueuer] Initialized with Postgres host: %s, database: %s", pg_config.host, pg_config.database)

    def enqueue_file(
        self,
        *,
        kind: Literal["post", "comment"],
        file_path: str,
        created_at: Optional[datetime] = None,
    ) -> None:
        """
        Insert a single row for this file into the appropriate table.
        """
        if kind not in ("post", "comment"):
            raise ValueError(f"kind must be 'post' or 'comment', got: {kind}")

        # Safety check: assert thor_worker_id is present and non-empty
        if not self.thor_worker_id or self.thor_worker_id.strip() == '':
            error_msg = (
                f"thor_worker_id is missing or empty in FileEnqueuer. "
                f"Cannot insert {kind} file '{file_path}' without worker ID. "
                f"This indicates a configuration error."
            )
            logger.error(error_msg)
            raise RuntimeError(error_msg)

        table = "crawled_posts" if kind == "post" else "crawled_comments"
        ts = created_at or datetime.now(timezone.utc)

        sql = f"""
            INSERT INTO {table} (file_path, created_at, is_ingested, ingest_attempts, thor_worker_id)
            VALUES (%s, %s, %s, %s, %s)
        """
        params = (file_path, ts, False, 0, self.thor_worker_id)

        dsn = self._pg_config.dsn()

        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
            conn.commit()
        logger.info("[FileEnqueuer] Enqueued file '%s' into table '%s' with thor_worker_id='%s'", file_path, table, self.thor_worker_id)
