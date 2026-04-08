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
from typing import Any, Optional
import requests

from igscraper.paths import (
    chrome_executable_path_after_extract,
    chromedriver_executable_path_after_extract,
    get_cached_config_path,
    get_chrome_extract_dir,
    get_chromedriver_extract_dir,
    get_slug_cache_dir,
    resolve_cft_platform,
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


def run_bootstrap(
    *,
    force_browser: bool = False,
    force_config: bool = False,
) -> BootstrapResult:
    """
    Download stable Chrome + ChromeDriver for this OS/arch into ``~/.slug/browser/...``.

    If ``~/.slug/config.toml`` is missing, writes the bundled sample (unless *force_config*
    is used only when combined with ensure_sample — actually force_config overwrites config).
    """
    try:
        cft_platform = resolve_cft_platform()
    except OSError as e:
        return BootstrapResult(
            ok=False,
            message=str(e),
            cft_platform="",
            chrome_version="",
        )

    chrome_dir = get_chrome_extract_dir(cft_platform)
    driver_dir = get_chromedriver_extract_dir(cft_platform)
    chrome_bin = chrome_executable_path_after_extract(cft_platform, chrome_dir)
    driver_bin = chromedriver_executable_path_after_extract(cft_platform, driver_dir)

    if (
        not force_browser
        and chrome_bin.is_file()
        and driver_bin.is_file()
    ):
        cfg_path, cfg_written = ensure_sample_config_in_cache(force=force_config)
        return BootstrapResult(
            ok=True,
            message="Chrome and ChromeDriver already present in cache; skipped download.",
            cft_platform=cft_platform,
            chrome_version="(cached)",
            chrome_bin=chrome_bin,
            chromedriver_bin=driver_bin,
            config_path=cfg_path,
            config_written=cfg_written,
        )

    try:
        version, chrome_url, driver_url = _fetch_stable_download_urls(cft_platform)
    except RuntimeError as e:
        return BootstrapResult(
            ok=False,
            message=str(e),
            cft_platform=cft_platform,
            chrome_version="",
        )

    get_slug_cache_dir().mkdir(parents=True, exist_ok=True)
    if force_browser:
        if chrome_dir.exists():
            shutil.rmtree(chrome_dir)
        if driver_dir.exists():
            shutil.rmtree(driver_dir)

    with tempfile.TemporaryDirectory(prefix="slug-cft-") as tmp:
        tdir = Path(tmp)
        c_zip = tdir / "chrome.zip"
        d_zip = tdir / "chromedriver.zip"
        try:
            _download_file(chrome_url, c_zip)
            _download_file(driver_url, d_zip)
        except requests.RequestException as e:
            return BootstrapResult(
                ok=False,
                message=f"Download failed: {e}",
                cft_platform=cft_platform,
                chrome_version=version,
            )

        try:
            _extract_zip(c_zip, chrome_dir)
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

    return BootstrapResult(
        ok=True,
        message="Bootstrap complete.",
        cft_platform=cft_platform,
        chrome_version=version,
        chrome_bin=chrome_bin,
        chromedriver_bin=driver_bin,
        config_path=cfg_path,
        config_written=cfg_written,
    )
