"""
Local Postgres defaults and ``~/.slug/.env`` persistence.

Bootstrap and ``FileEnqueuer`` share the same defaults so a first-time local run
does not fail on an empty ``PUGSY_PG_DATABASE``. Production must still set
explicit credentials (and usually a non-default database name).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from igscraper.paths import get_cached_dotenv_path, get_slug_cache_dir

# Typical local Docker / Homebrew Postgres defaults (see README).
DEFAULT_PG_HOST = "localhost"
DEFAULT_PG_PORT = 5433
DEFAULT_PG_USER = "postgres"
DEFAULT_PG_PASSWORD = ""
DEFAULT_PG_DATABASE = "postgres"


@dataclass(frozen=True)
class ResolvedPgEnv:
    host: str
    port: int
    user: str
    password: str
    database: str
    used_default_database: bool


def resolve_pg_env_for_bootstrap(*, apply_default_database: bool) -> ResolvedPgEnv:
    """
    Read ``PUGSY_PG_*`` from the environment with the same fallbacks as bootstrap.

    When *apply_default_database* is true and ``PUGSY_PG_DATABASE`` is unset or
    blank, use :data:`DEFAULT_PG_DATABASE` (``postgres``).
    """
    host = (os.environ.get("PUGSY_PG_HOST") or DEFAULT_PG_HOST).strip()
    port = int((os.environ.get("PUGSY_PG_PORT") or str(DEFAULT_PG_PORT)).strip())
    user = (os.environ.get("PUGSY_PG_USER") or DEFAULT_PG_USER).strip()
    password = os.environ.get("PUGSY_PG_PASSWORD") or ""
    database = (os.environ.get("PUGSY_PG_DATABASE") or "").strip()
    used_default = False
    if not database and apply_default_database:
        database = DEFAULT_PG_DATABASE
        used_default = True
    return ResolvedPgEnv(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        used_default_database=used_default,
    )


def write_cached_dotenv(resolved: ResolvedPgEnv) -> Path:
    """
    Write ``~/.slug/.env`` with the effective connection values.

    Called after a successful ``bootstrap`` Postgres setup so later processes
    and ``FileEnqueuer`` pick up the same DSN without extra shell wiring.
    """
    path = get_cached_dotenv_path()
    get_slug_cache_dir().mkdir(parents=True, exist_ok=True)
    lines = [
        "# Slug-Ig-Crawler — Postgres (local defaults). Override via shell env or project .env.",
        f"PUGSY_PG_HOST={resolved.host}",
        f"PUGSY_PG_PORT={resolved.port}",
        f"PUGSY_PG_USER={resolved.user}",
        f"PUGSY_PG_PASSWORD={resolved.password}",
        f"PUGSY_PG_DATABASE={resolved.database}",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def apply_resolved_to_environ(resolved: ResolvedPgEnv) -> None:
    """Mirror resolved values into ``os.environ`` for the current process."""
    os.environ["PUGSY_PG_HOST"] = resolved.host
    os.environ["PUGSY_PG_PORT"] = str(resolved.port)
    os.environ["PUGSY_PG_USER"] = resolved.user
    os.environ["PUGSY_PG_PASSWORD"] = resolved.password
    os.environ["PUGSY_PG_DATABASE"] = resolved.database


def load_dotenv_for_app() -> None:
    """
    Load env files in precedence order:

    1. ``~/.slug/.env`` if present (local cache; does not override existing vars).
    2. ``ENV_FILE`` or ``.env`` in the current working directory if present
       (project overrides cache).
    """
    cache_path = get_cached_dotenv_path()
    if cache_path.is_file():
        load_dotenv(dotenv_path=cache_path, override=False)
    project = os.environ.get("ENV_FILE", ".env")
    p = Path(project).expanduser()
    if p.is_file():
        load_dotenv(dotenv_path=str(p), override=True)
