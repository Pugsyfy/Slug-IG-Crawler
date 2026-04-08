"""Tests for local Postgres defaults and ~/.slug/.env helpers."""
from __future__ import annotations

import os

from igscraper.pg_env import (
    DEFAULT_PG_DATABASE,
    ResolvedPgEnv,
    apply_resolved_to_environ,
    resolve_pg_env_for_bootstrap,
    write_cached_dotenv,
)


def test_resolve_uses_default_database_when_unset(monkeypatch):
    monkeypatch.delenv("PUGSY_PG_DATABASE", raising=False)
    r = resolve_pg_env_for_bootstrap(apply_default_database=True)
    assert r.database == DEFAULT_PG_DATABASE
    assert r.used_default_database is True


def test_resolve_respects_explicit_database(monkeypatch):
    monkeypatch.setenv("PUGSY_PG_DATABASE", "mydb")
    r = resolve_pg_env_for_bootstrap(apply_default_database=True)
    assert r.database == "mydb"
    assert r.used_default_database is False


def test_write_cached_dotenv_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    resolved = ResolvedPgEnv(
        host="h",
        port=5432,
        user="u",
        password="p",
        database="d",
        used_default_database=False,
    )
    path = write_cached_dotenv(resolved)
    assert path.name == ".env"
    text = path.read_text(encoding="utf-8")
    assert "PUGSY_PG_HOST=h" in text
    assert "PUGSY_PG_DATABASE=d" in text


def test_apply_resolved_to_environ(monkeypatch):
    monkeypatch.delenv("PUGSY_PG_DATABASE", raising=False)
    r = resolve_pg_env_for_bootstrap(apply_default_database=True)
    apply_resolved_to_environ(r)
    assert os.environ["PUGSY_PG_DATABASE"] == DEFAULT_PG_DATABASE
