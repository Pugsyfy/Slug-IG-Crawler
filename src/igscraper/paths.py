"""
Centralized paths for Slug-Ig-Crawler user cache under ``~/.slug``.
"""
from __future__ import annotations

import platform
import sys
from pathlib import Path
from typing import Optional, Tuple

SLUG_CACHE_DIRNAME = ".slug"
CACHED_CONFIG_FILENAME = "config.toml"
BROWSER_SUBDIR = "browser"

# Chrome for Testing JSON platform keys (linux64, mac-arm64, mac-x64).
CftPlatform = str


def get_slug_cache_dir() -> Path:
    """Return ``~/.slug`` (created lazily by callers that write)."""
    return Path.home() / SLUG_CACHE_DIRNAME


def get_cached_config_path() -> Path:
    """Default user config location: ``~/.slug/config.toml``."""
    return get_slug_cache_dir() / CACHED_CONFIG_FILENAME


def resolve_cft_platform() -> CftPlatform:
    """
    Map OS/arch to Chrome for Testing ``platform`` field.

    Supports macOS and Linux only (raises on other OS).
    """
    if sys.platform == "linux":
        return "linux64"
    if sys.platform == "darwin":
        machine = platform.machine().lower()
        if machine in ("arm64", "aarch64"):
            return "mac-arm64"
        return "mac-x64"
    raise OSError(
        f"Unsupported platform for bundled Chrome bootstrap: {sys.platform!r}. "
        "Supported: macOS, Linux."
    )


def get_browser_platform_dir(cft_platform: Optional[CftPlatform] = None) -> Path:
    """``~/.slug/browser/<cft_platform>/``."""
    plat = cft_platform or resolve_cft_platform()
    return get_slug_cache_dir() / BROWSER_SUBDIR / plat


def get_chrome_extract_dir(cft_platform: Optional[CftPlatform] = None) -> Path:
    """Directory where the Chrome zip is extracted."""
    return get_browser_platform_dir(cft_platform) / "chrome"


def get_chromedriver_extract_dir(cft_platform: Optional[CftPlatform] = None) -> Path:
    """Directory where the ChromeDriver zip is extracted."""
    return get_browser_platform_dir(cft_platform) / "chromedriver"


def chrome_executable_path_after_extract(cft_platform: str, chrome_root: Path) -> Path:
    """Expected Chrome binary path relative to *chrome* extract root."""
    if cft_platform == "linux64":
        return chrome_root / "chrome-linux64" / "chrome"
    if cft_platform == "mac-arm64":
        return (
            chrome_root
            / "chrome-mac-arm64"
            / "Google Chrome for Testing.app"
            / "Contents"
            / "MacOS"
            / "Google Chrome for Testing"
        )
    if cft_platform == "mac-x64":
        return (
            chrome_root
            / "chrome-mac-x64"
            / "Google Chrome for Testing.app"
            / "Contents"
            / "MacOS"
            / "Google Chrome for Testing"
        )
    raise ValueError(f"Unknown CFT platform: {cft_platform!r}")


def chromedriver_executable_path_after_extract(
    cft_platform: str, driver_root: Path
) -> Path:
    """Expected chromedriver binary path relative to *chromedriver* extract root."""
    if cft_platform == "linux64":
        return driver_root / "chromedriver-linux64" / "chromedriver"
    if cft_platform == "mac-arm64":
        return driver_root / "chromedriver-mac-arm64" / "chromedriver"
    if cft_platform == "mac-x64":
        return driver_root / "chromedriver-mac-x64" / "chromedriver"
    raise ValueError(f"Unknown CFT platform: {cft_platform!r}")


def get_cached_browser_binaries(
    cft_platform: Optional[CftPlatform] = None,
) -> Tuple[Optional[Path], Optional[Path]]:
    """
    Return ``(chrome_bin, chromedriver_bin)`` if both cached files exist and are files.

    Paths match layout produced by :mod:`igscraper.bootstrap`.
    """
    try:
        plat = cft_platform or resolve_cft_platform()
    except OSError:
        return None, None

    chrome_root = get_chrome_extract_dir(plat)
    driver_root = get_chromedriver_extract_dir(plat)
    c = chrome_executable_path_after_extract(plat, chrome_root)
    d = chromedriver_executable_path_after_extract(plat, driver_root)
    if c.is_file() and d.is_file():
        return c, d
    return None, None


def slug_cache_has_valid_browser_pair(
    cft_platform: Optional[CftPlatform] = None,
) -> bool:
    c, d = get_cached_browser_binaries(cft_platform)
    return c is not None and d is not None
