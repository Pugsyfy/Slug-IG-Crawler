"""
Download Chrome for Testing (stable) + matching ChromeDriver into ``~/.slug`` and
optionally install the bundled sample config at ``~/.slug/config.toml``.
"""
from __future__ import annotations

import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional
import requests
import psycopg

from igscraper.paths import (
    chrome_executable_path_after_extract,
    chromedriver_executable_path_after_extract,
    get_cached_config_path,
    get_chrome_extract_dir,
    get_chromedriver_extract_dir,
    get_slug_cache_dir,
    resolve_cft_platform,
)
from igscraper.pg_env import (
    apply_resolved_to_environ,
    resolve_pg_env_for_bootstrap,
    write_cached_dotenv,
)

CFT_LKG_URL = (
    "https://googlechromelabs.github.io/chrome-for-testing/"
    "last-known-good-versions-with-downloads.json"
)


@dataclass
class BootstrapResult:
    ok: bool
    message: str
    cft_platform: str
    chrome_version: str
    chrome_bin: Optional[Path] = None
    chromedriver_bin: Optional[Path] = None
    config_path: Optional[Path] = None
    config_written: bool = False
    postgres_setup_attempted: bool = False
    postgres_setup_ok: Optional[bool] = None
    postgres_message: str = ""


def read_bundled_sample_config_text() -> str:
    """Load packaged ``config.example.toml`` (wheel-safe)."""
    try:
        from importlib.resources import files

        p = files("igscraper").joinpath("config.example.toml")
        return p.read_text(encoding="utf-8")
    except Exception:
        # Editable / dev: fall back next to this package
        here = Path(__file__).resolve().parent / "config.example.toml"
        if here.is_file():
            return here.read_text(encoding="utf-8")
    raise FileNotFoundError(
        "Bundled config.example.toml not found in package; reinstall slug-ig-crawler."
    )


def _fetch_stable_download_urls(cft_platform: str) -> tuple[str, str, str]:
    """Return (chrome_version, chrome_zip_url, chromedriver_zip_url)."""
    try:
        r = requests.get(CFT_LKG_URL, timeout=60)
        r.raise_for_status()
        data: dict[str, Any] = r.json()
    except requests.RequestException as e:
        raise RuntimeError(f"Failed to fetch Chrome for Testing metadata: {e}") from e

    stable = (data.get("channels") or {}).get("Stable")
    if not stable:
        raise RuntimeError("Chrome for Testing JSON missing channels.Stable")

    version = str(stable.get("version") or "")
    downloads = stable.get("downloads") or {}
    chrome_list = downloads.get("chrome") or []
    driver_list = downloads.get("chromedriver") or []

    def _pick(entries: list[dict[str, Any]], key: str) -> Optional[str]:
        for item in entries:
            if item.get("platform") == key:
                return str(item.get("url") or "")
        return None

    cu = _pick(chrome_list, cft_platform)
    du = _pick(driver_list, cft_platform)
    if not cu or not du:
        raise RuntimeError(
            f"No Stable Chrome/ChromeDriver URLs for platform {cft_platform!r} in metadata."
        )
    return version, cu, du


def _download_file(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=300) as resp:
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 256):
                if chunk:
                    f.write(chunk)


def _extract_zip(zip_path: Path, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(dest_dir)


def _chmod_plus_x(path: Path) -> None:
    if not path.is_file():
        return
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def ensure_sample_config_in_cache(*, force: bool = False) -> tuple[Path, bool]:
    """
    Copy bundled sample to ``~/.slug/config.toml`` if missing (unless *force*).

    Returns ``(path, written)``.
    """
    dest = get_cached_config_path()
    get_slug_cache_dir().mkdir(parents=True, exist_ok=True)
    if dest.is_file() and not force:
        return dest, False
    text = read_bundled_sample_config_text()
    dest.write_text(text, encoding="utf-8")
    return dest, True


def _default_postgres_setup_sql_path() -> Path:
    # src/igscraper/bootstrap.py -> repo root/scripts/postgres_setup.sql
    return Path(__file__).resolve().parents[2] / "scripts" / "postgres_setup.sql"


def _load_default_postgres_setup_sql() -> tuple[Optional[str], str]:
    """
    Load default postgres setup SQL text.

    Priority:
    1) Bundled package data: igscraper/postgres_setup.sql (works after pip install)
    2) Repository fallback: scripts/postgres_setup.sql (editable/source runs)
    """
    try:
        from importlib.resources import files

        p = files("igscraper").joinpath("postgres_setup.sql")
        return p.read_text(encoding="utf-8"), "package:igscraper/postgres_setup.sql"
    except Exception:
        pass

    fallback = _default_postgres_setup_sql_path()
    if fallback.is_file():
        return fallback.read_text(encoding="utf-8"), str(fallback)
    return None, f"{fallback} (missing)"


def _run_postgres_setup(
    *,
    sql_text: str,
    sql_source: str,
    progress: Optional[Callable[[str], None]] = None,
) -> tuple[bool, str]:
    def _emit(msg: str) -> None:
        if progress:
            progress(msg)

    resolved = resolve_pg_env_for_bootstrap(apply_default_database=True)
    host = resolved.host
    port = resolved.port
    user = resolved.user
    password = resolved.password
    database = resolved.database

    if resolved.used_default_database:
        _emit(
            "PUGSY_PG_DATABASE not set; using local default "
            f"'{database}' (override with env or ~/.slug/.env)."
        )

    _emit(
        "Postgres setup target -> "
        f"host={host} port={port} db={database} user={user}"
    )
    _emit(f"Loading SQL from {sql_source}")
    if not sql_text.strip():
        return False, f"Postgres setup SQL is empty: {sql_source}"

    dsn = (
        f"host={host} port={port} dbname={database} "
        f"user={user} password={password}"
    )
    try:
        with psycopg.connect(dsn, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                _emit("Executing postgres_setup.sql (idempotent statements)...")
                cur.execute(sql_text)
                conn.commit()
                cur.execute(
                    "SELECT to_regclass('public.crawled_posts'), "
                    "to_regclass('public.crawled_comments')"
                )
                posts_tbl, comments_tbl = cur.fetchone()
        if posts_tbl and comments_tbl:
            dotenv_path = write_cached_dotenv(resolved)
            apply_resolved_to_environ(resolved)
            return (
                True,
                "Postgres bootstrap complete: required tables are present. "
                f"Wrote {dotenv_path}",
            )
        return (
            False,
            "Postgres setup ran but required tables were not detected "
            "(crawled_posts, crawled_comments).",
        )
    except Exception as e:
        return False, f"Postgres setup failed: {e}"


def run_bootstrap(
    *,
    force_browser: bool = False,
    force_config: bool = False,
    setup_postgres: bool = True,
    postgres_sql_file: Optional[str] = None,
    progress: Optional[Callable[[str], None]] = None,
) -> BootstrapResult:
    """
    Download stable Chrome + ChromeDriver for this OS/arch into ``~/.slug/browser/...``.

    If ``~/.slug/config.toml`` is missing, writes the bundled sample (unless *force_config*
    is used only when combined with ensure_sample — actually force_config overwrites config).
    """
    def _emit(msg: str) -> None:
        if progress:
            progress(msg)

    try:
        cft_platform = resolve_cft_platform()
    except OSError as e:
        return BootstrapResult(
            ok=False,
            message=str(e),
            cft_platform="",
            chrome_version="",
        )

    _emit(f"Resolved CFT platform: {cft_platform}")
    chrome_dir = get_chrome_extract_dir(cft_platform)
    driver_dir = get_chromedriver_extract_dir(cft_platform)
    chrome_bin = chrome_executable_path_after_extract(cft_platform, chrome_dir)
    driver_bin = chromedriver_executable_path_after_extract(cft_platform, driver_dir)
    _emit(f"Chrome cache dir: {chrome_dir}")
    _emit(f"ChromeDriver cache dir: {driver_dir}")

    if (
        not force_browser
        and chrome_bin.is_file()
        and driver_bin.is_file()
    ):
        _emit("Found cached Chrome + ChromeDriver pair; skipping downloads.")
        cfg_path, cfg_written = ensure_sample_config_in_cache(force=force_config)
        _emit(
            f"Sample config {'written' if cfg_written else 'already present'} at {cfg_path}"
        )
        pg_ok: Optional[bool] = None
        pg_msg = ""
        if setup_postgres:
            _emit("Running Postgres setup...")
            sql_text: Optional[str] = None
            sql_source = ""
            if postgres_sql_file:
                sql_path = Path(postgres_sql_file).expanduser().resolve()
                if not sql_path.is_file():
                    pg_ok, pg_msg = False, f"Postgres setup SQL file not found: {sql_path}"
                else:
                    sql_text = sql_path.read_text(encoding="utf-8")
                    sql_source = str(sql_path)
            else:
                sql_text, sql_source = _load_default_postgres_setup_sql()
                if sql_text is None:
                    pg_ok, pg_msg = False, f"Postgres setup SQL file not found: {sql_source}"

            if pg_ok is False:
                _emit(pg_msg)
                return BootstrapResult(
                    ok=False,
                    message=pg_msg,
                    cft_platform=cft_platform,
                    chrome_version="(cached)",
                    chrome_bin=chrome_bin,
                    chromedriver_bin=driver_bin,
                    config_path=cfg_path,
                    config_written=cfg_written,
                    postgres_setup_attempted=True,
                    postgres_setup_ok=False,
                    postgres_message=pg_msg,
                )

            pg_ok, pg_msg = _run_postgres_setup(
                sql_text=sql_text or "",
                sql_source=sql_source,
                progress=progress,
            )
            _emit(pg_msg)
            if not pg_ok:
                return BootstrapResult(
                    ok=False,
                    message=pg_msg,
                    cft_platform=cft_platform,
                    chrome_version="(cached)",
                    chrome_bin=chrome_bin,
                    chromedriver_bin=driver_bin,
                    config_path=cfg_path,
                    config_written=cfg_written,
                    postgres_setup_attempted=True,
                    postgres_setup_ok=False,
                    postgres_message=pg_msg,
                )

        return BootstrapResult(
            ok=True,
            message="Chrome and ChromeDriver already present in cache; skipped download.",
            cft_platform=cft_platform,
            chrome_version="(cached)",
            chrome_bin=chrome_bin,
            chromedriver_bin=driver_bin,
            config_path=cfg_path,
            config_written=cfg_written,
            postgres_setup_attempted=setup_postgres,
            postgres_setup_ok=pg_ok,
            postgres_message=pg_msg,
        )

    _emit("Fetching latest stable Chrome for Testing metadata...")
    try:
        version, chrome_url, driver_url = _fetch_stable_download_urls(cft_platform)
    except RuntimeError as e:
        return BootstrapResult(
            ok=False,
            message=str(e),
            cft_platform=cft_platform,
            chrome_version="",
        )

    _emit(f"Stable Chrome version: {version}")
    _emit(f"Chrome zip URL: {chrome_url}")
    _emit(f"ChromeDriver zip URL: {driver_url}")

    get_slug_cache_dir().mkdir(parents=True, exist_ok=True)
    if force_browser:
        _emit("Force mode enabled; removing existing cached browser directories.")
        if chrome_dir.exists():
            shutil.rmtree(chrome_dir)
        if driver_dir.exists():
            shutil.rmtree(driver_dir)

    with tempfile.TemporaryDirectory(prefix="slug-cft-") as tmp:
        tdir = Path(tmp)
        c_zip = tdir / "chrome.zip"
        d_zip = tdir / "chromedriver.zip"
        try:
            _emit("Downloading Chrome zip...")
            _download_file(chrome_url, c_zip)
            _emit("Downloading ChromeDriver zip...")
            _download_file(driver_url, d_zip)
        except requests.RequestException as e:
            return BootstrapResult(
                ok=False,
                message=f"Download failed: {e}",
                cft_platform=cft_platform,
                chrome_version=version,
            )

        try:
            _emit("Extracting Chrome zip...")
            _extract_zip(c_zip, chrome_dir)
            _emit("Extracting ChromeDriver zip...")
            _extract_zip(d_zip, driver_dir)
        except zipfile.BadZipFile as e:
            return BootstrapResult(
                ok=False,
                message=f"Invalid zip from Chrome for Testing: {e}",
                cft_platform=cft_platform,
                chrome_version=version,
            )

    _chmod_plus_x(chrome_bin)
    _chmod_plus_x(driver_bin)
    _emit("Ensured executable permissions on browser binaries.")

    if not chrome_bin.is_file() or not driver_bin.is_file():
        return BootstrapResult(
            ok=False,
            message=(
                f"Extracted archives but binaries not found at:\n"
                f"  {chrome_bin}\n  {driver_bin}"
            ),
            cft_platform=cft_platform,
            chrome_version=version,
        )

    cfg_path, cfg_written = ensure_sample_config_in_cache(force=force_config)
    _emit(f"Sample config {'written' if cfg_written else 'already present'} at {cfg_path}")
    _emit("Bootstrap finished successfully.")

    pg_ok: Optional[bool] = None
    pg_msg = ""
    if setup_postgres:
        _emit("Running Postgres setup...")
        sql_text: Optional[str] = None
        sql_source = ""
        if postgres_sql_file:
            sql_path = Path(postgres_sql_file).expanduser().resolve()
            if not sql_path.is_file():
                pg_ok, pg_msg = False, f"Postgres setup SQL file not found: {sql_path}"
            else:
                sql_text = sql_path.read_text(encoding="utf-8")
                sql_source = str(sql_path)
        else:
            sql_text, sql_source = _load_default_postgres_setup_sql()
            if sql_text is None:
                pg_ok, pg_msg = False, f"Postgres setup SQL file not found: {sql_source}"

        if pg_ok is False:
            _emit(pg_msg)
            return BootstrapResult(
                ok=False,
                message=pg_msg,
                cft_platform=cft_platform,
                chrome_version=version,
                chrome_bin=chrome_bin,
                chromedriver_bin=driver_bin,
                config_path=cfg_path,
                config_written=cfg_written,
                postgres_setup_attempted=True,
                postgres_setup_ok=False,
                postgres_message=pg_msg,
            )

        pg_ok, pg_msg = _run_postgres_setup(
            sql_text=sql_text or "",
            sql_source=sql_source,
            progress=progress,
        )
        _emit(pg_msg)
        if not pg_ok:
            return BootstrapResult(
                ok=False,
                message=pg_msg,
                cft_platform=cft_platform,
                chrome_version=version,
                chrome_bin=chrome_bin,
                chromedriver_bin=driver_bin,
                config_path=cfg_path,
                config_written=cfg_written,
                postgres_setup_attempted=True,
                postgres_setup_ok=False,
                postgres_message=pg_msg,
            )

    return BootstrapResult(
        ok=True,
        message="Bootstrap complete.",
        cft_platform=cft_platform,
        chrome_version=version,
        chrome_bin=chrome_bin,
        chromedriver_bin=driver_bin,
        config_path=cfg_path,
        config_written=cfg_written,
        postgres_setup_attempted=setup_postgres,
        postgres_setup_ok=pg_ok,
        postgres_message=pg_msg,
    )
