from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Optional

import psycopg
import logging


logger = logging.getLogger(__name__)

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
            port=int(os.environ.get("PUGSY_PG_PORT", "5432")),
            user=os.environ.get("PUGSY_PG_USER", "pugsy_user"),
            password=os.environ.get("PUGSY_PG_PASSWORD", "pugsy_pass"),
            database=os.environ.get("PUGSY_PG_DATABASE", "pugsy_ingestion"),
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

    Schema assumed (no shortcode):

        CREATE TABLE crawled_posts (
            id              serial primary key,
            file_path       text not null,
            created_at      timestamptz not null,
            is_ingested     boolean not null default false,
            ingest_attempts int not null default 0,
            last_ingested_at timestamptz,
            last_error      text
        );

        -- same for crawled_comments
    """

    def __init__(self, pg_config: PostgresConfig) -> None:
        self._pg_config = pg_config
        logger.info("[FileEnqueuer] Initialized with Postgres host: %s, database: %s", pg_config.host, pg_config.database)

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

        table = "crawled_posts" if kind == "post" else "crawled_comments"
        ts = created_at or datetime.now(timezone.utc)

        sql = f"""
            INSERT INTO {table} (file_path, created_at, is_ingested, ingest_attempts)
            VALUES (%s, %s, %s, %s)
        """
        params = (file_path, ts, False, 0)

        dsn = self._pg_config.dsn()

        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
            conn.commit()
        logger.info("[FileEnqueuer] Enqueued file '%s' into table '%s'", file_path, table)
