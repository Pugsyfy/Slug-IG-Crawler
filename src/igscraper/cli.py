"""
Command-line interface for Slug-Ig-Crawler.

This script serves as the main entry point for running the scraper from the
command line. It handles parsing command-line arguments and initiating the
scraping pipeline.

Commands:
  run (default)     Run the pipeline; ``--config`` optional if ``~/.slug/config.toml`` exists.
  bootstrap       Download stable Chrome + ChromeDriver into ``~/.slug`` and install sample config.
  show-config     Print bundled sample TOML plus cached config/cookie paths.
  save-cookie     Capture Instagram login cookies into ``~/.slug/cookies``.
  list-cookies    Print only cached cookie JSON paths.
  version         Print installed package version.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# When running from a source checkout (`src/igscraper/...`), add `src/` so imports work.
# When installed as a wheel, site-packages already provides `igscraper`.
_pkg_dir = Path(__file__).resolve().parent
_src = _pkg_dir.parent
if _src.name == "src" and str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from igscraper.bootstrap import read_bundled_sample_config_text, run_bootstrap
from igscraper import __version__
from igscraper.login_Save_cookie import capture_login_cookies
from igscraper.paths import (
    CACHED_CONFIG_FILENAME,
    get_cached_config_path,
    get_cookie_cache_dir,
    get_slug_cache_dir,
    slug_cache_has_valid_browser_pair,
)


def _resolve_config_path(explicit: str | None) -> str:
    """Prefer explicit path, then ``~/.slug/config.toml`` if it exists."""
    if explicit:
        p = Path(explicit).expanduser()
        if not p.is_file():
            raise SystemExit(f"Config file not found: {p}")
        return str(p.resolve())
    cached = get_cached_config_path()
    if cached.is_file():
        return str(cached.resolve())
    raise SystemExit(
        "No config file specified and ~/.slug/config.toml not found.\n"
        "  Pass --config PATH, or run: Slug-Ig-Crawler bootstrap\n"
        "  (installs sample config to ~/.slug/config.toml), then edit cookies and settings."
    )


def _maybe_warn_browser_cache() -> None:
    """If no explicit env override and no cached pair, stderr hint (suppressible)."""
    if os.environ.get("IGSCRAPER_SILENT_BROWSER_CACHE_WARN", "").strip() in (
        "1",
        "true",
        "yes",
    ):
        return
    if os.environ.get("CHROME_BIN") or os.environ.get("CHROMEDRIVER_BIN"):
        return
    if slug_cache_has_valid_browser_pair():
        return
    print(
        "Slug-Ig-Crawler: no Chrome/ChromeDriver in ~/.slug/browser/ and CHROME_BIN/CHROMEDRIVER_BIN unset.\n"
        "  For a matching stable pair, run: Slug-Ig-Crawler bootstrap\n"
        "  (cache: ~/.slug). Silence this message: IGSCRAPER_SILENT_BROWSER_CACHE_WARN=1\n",
        file=sys.stderr,
    )


def _cmd_run(args: argparse.Namespace) -> None:
    # Import lazily so non-run commands (bootstrap/version/etc.) do not pull heavy deps.
    from igscraper.pipeline import Pipeline

    config_path = _resolve_config_path(args.config)
    _maybe_warn_browser_cache()
    pipeline = Pipeline(config_path=config_path)
    pipeline.run()


def _cmd_bootstrap(args: argparse.Namespace) -> None:
    print("Starting bootstrap...")
    print(f"  Cache root: {get_slug_cache_dir()}")
    print(f"  Config path: {get_cached_config_path()}")
    print(f"  Force browser download: {bool(args.force)}")
    print(f"  Force config overwrite: {bool(args.force_config)}")

    res = run_bootstrap(
        force_browser=args.force,
        force_config=args.force_config,
        progress=lambda msg: print(f"  - {msg}"),
    )
    if not res.ok:
        raise SystemExit(res.message)
    print(res.message)
    print(f"  Platform (Chrome for Testing): {res.cft_platform}")
    print(f"  Chrome version: {res.chrome_version}")
    if res.chrome_bin:
        print(f"  Chrome:       {res.chrome_bin}")
    if res.chromedriver_bin:
        print(f"  ChromeDriver: {res.chromedriver_bin}")
    if res.config_path:
        print(f"  Sample config: {res.config_path}" + (" (written)" if res.config_written else " (already existed)"))


def _cmd_show_config(_args: argparse.Namespace) -> None:
    cached = get_cached_config_path()
    print("=== Bundled sample config (config.example.toml) ===\n")
    print(read_bundled_sample_config_text().rstrip() + "\n")
    print("=== User cache ===\n")
    print(f"  ~/.slug             : {get_slug_cache_dir()}")
    print(f"  ~/.slug/config.toml : {cached}")
    print(f"  exists: {cached.is_file()}")
    if cached.is_file():
        print(f"  resolved: {cached.resolve()}")
    config_files = _list_cache_config_paths()
    print(f"\n  cached config files ({len(config_files)}):")
    for p in config_files:
        print(f"    - {p}")

    cookie_files = _list_cookie_paths()
    print(f"\n  cached cookie files ({len(cookie_files)}):")
    for p in cookie_files:
        print(f"    - {p}")


def _list_cache_config_paths() -> list[Path]:
    """Return absolute paths to TOML files under ~/.slug."""
    root = get_slug_cache_dir()
    if not root.is_dir():
        return []
    return sorted(
        [p.resolve() for p in root.glob("**/*.toml") if p.is_file()],
        key=lambda p: str(p),
    )


def _list_cookie_paths() -> list[Path]:
    """Return absolute paths to cookie JSON files under ~/.slug/cookies."""
    cookie_dir = get_cookie_cache_dir()
    if not cookie_dir.is_dir():
        return []
    return sorted(
        [p.resolve() for p in cookie_dir.glob("*.json") if p.is_file()],
        key=lambda p: str(p),
    )


def _cmd_save_cookie(args: argparse.Namespace) -> None:
    result = capture_login_cookies(args.username)
    print("Cookie capture complete.")
    print(f"  Username:        {result.username}")
    print(f"  Browser version: {result.browser_version}")
    print(f"  Cookie count:    {result.cookie_count}")
    print(f"  Cookie file:     {result.cookie_path}")
    print(f"  Latest pointer:  {result.latest_path}")


def _cmd_list_cookies(_args: argparse.Namespace) -> None:
    for p in _list_cookie_paths():
        print(str(p))


def _cmd_version(_args: argparse.Namespace) -> None:
    print(__version__)


def main() -> None:
    argv = sys.argv[1:]
    # Subcommands when first token is a known command
    if argv and argv[0] in (
        "run",
        "bootstrap",
        "show-config",
        "save-cookie",
        "list-cookies",
        "version",
    ):
        cmd = argv[0]
        rest = argv[1:]
    else:
        cmd = "run"
        rest = argv

    if cmd == "bootstrap":
        p = argparse.ArgumentParser(prog="Slug-Ig-Crawler", description="Slug-Ig-Crawler")
        p.add_argument(
            "--force",
            action="store_true",
            help="Re-download Chrome/ChromeDriver even if cache exists.",
        )
        p.add_argument(
            "--force-config",
            action="store_true",
            help="Overwrite ~/.slug/config.toml with the bundled sample.",
        )
        args = p.parse_args(rest)
        _cmd_bootstrap(args)
        return

    if cmd == "show-config":
        p = argparse.ArgumentParser(prog="Slug-Ig-Crawler", description="Slug-Ig-Crawler")
        args = p.parse_args(rest)
        _cmd_show_config(args)
        return

    if cmd == "save-cookie":
        p = argparse.ArgumentParser(prog="Slug-Ig-Crawler", description="Slug-Ig-Crawler")
        p.add_argument(
            "--username",
            required=True,
            help="Instagram username for naming the saved cookie file.",
        )
        args = p.parse_args(rest)
        _cmd_save_cookie(args)
        return

    if cmd == "list-cookies":
        p = argparse.ArgumentParser(prog="Slug-Ig-Crawler", description="Slug-Ig-Crawler")
        args = p.parse_args(rest)
        _cmd_list_cookies(args)
        return

    if cmd == "version":
        p = argparse.ArgumentParser(prog="Slug-Ig-Crawler", description="Slug-Ig-Crawler")
        args = p.parse_args(rest)
        _cmd_version(args)
        return

    # run
    run_p = argparse.ArgumentParser(prog="Slug-Ig-Crawler", description="Slug-Ig-Crawler")
    run_p.add_argument(
        "--config",
        default=None,
        help=(
            "Path to config TOML. If omitted, uses ~/.slug/config.toml when that file exists "
            f"(default path: ~/.slug/{CACHED_CONFIG_FILENAME})."
        ),
    )
    args = run_p.parse_args(rest)
    _cmd_run(args)


if __name__ == "__main__":
    main()
