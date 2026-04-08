"""Tests for ~/.slug cache paths, CLI config resolution, and Selenium binary precedence."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from igscraper.backends.selenium_backend import SeleniumBackend
from igscraper.paths import (
    chrome_executable_path_after_extract,
    chromedriver_executable_path_after_extract,
    get_cached_browser_binaries,
    get_cached_config_path,
    resolve_cft_platform,
)


def test_resolve_cft_platform_linux_or_mac():
    plat = resolve_cft_platform()
    assert plat in ("linux64", "mac-arm64", "mac-x64")


def test_cached_config_path_respects_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert get_cached_config_path() == tmp_path / ".slug" / "config.toml"


def test_get_cached_browser_binaries_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    c, d = get_cached_browser_binaries()
    assert c is None and d is None


def test_get_cached_browser_binaries_present(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    plat = resolve_cft_platform()
    chrome_root = tmp_path / ".slug" / "browser" / plat / "chrome"
    driver_root = tmp_path / ".slug" / "browser" / plat / "chromedriver"
    cbin = chrome_executable_path_after_extract(plat, chrome_root)
    dbin = chromedriver_executable_path_after_extract(plat, driver_root)
    cbin.parent.mkdir(parents=True, exist_ok=True)
    dbin.parent.mkdir(parents=True, exist_ok=True)
    cbin.write_bytes(b"")
    dbin.write_bytes(b"")

    c, d = get_cached_browser_binaries()
    assert c == cbin.resolve()
    assert d == dbin.resolve()


def test_resolve_config_path_explicit_missing():
    from igscraper import cli

    with pytest.raises(SystemExit):
        cli._resolve_config_path("/nonexistent/config.toml")


def test_resolve_config_path_explicit_ok(tmp_path):
    from igscraper import cli

    p = tmp_path / "c.toml"
    p.write_text("[main]\nmode = 1\n", encoding="utf-8")
    out = cli._resolve_config_path(str(p))
    assert out == str(p.resolve())


def test_resolve_config_path_autoload_cached(monkeypatch, tmp_path):
    from igscraper import cli

    monkeypatch.setenv("HOME", str(tmp_path))
    cached = tmp_path / ".slug" / "config.toml"
    cached.parent.mkdir(parents=True)
    cached.write_text("[x]", encoding="utf-8")
    out = cli._resolve_config_path(None)
    assert out == str(cached.resolve())


def test_resolve_config_path_no_cached_raises(monkeypatch, tmp_path):
    from igscraper import cli

    monkeypatch.setenv("HOME", str(tmp_path))
    with pytest.raises(SystemExit) as ei:
        cli._resolve_config_path(None)
    assert "bootstrap" in str(ei.value).lower() or "bootstrap" in str(ei.value)


def test_selenium_resolve_uses_cache_when_unset(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    plat = resolve_cft_platform()
    chrome_root = tmp_path / ".slug" / "browser" / plat / "chrome"
    driver_root = tmp_path / ".slug" / "browser" / plat / "chromedriver"
    cbin = chrome_executable_path_after_extract(plat, chrome_root)
    dbin = chromedriver_executable_path_after_extract(plat, driver_root)
    cbin.parent.mkdir(parents=True, exist_ok=True)
    dbin.parent.mkdir(parents=True, exist_ok=True)
    cbin.write_bytes(b"")
    dbin.write_bytes(b"")

    monkeypatch.delenv("CHROME_BIN", raising=False)
    monkeypatch.delenv("CHROMEDRIVER_BIN", raising=False)

    backend = SeleniumBackend.__new__(SeleniumBackend)
    backend.config = SimpleNamespace(
        main=SimpleNamespace(
            use_docker=False,
            chrome_binary_path=None,
            chromedriver_binary_path=None,
        )
    )
    chrome, driver = backend._resolve_browser_binaries()
    assert chrome == str(cbin.resolve())
    assert driver == str(dbin.resolve())


def test_selenium_env_wins_over_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    plat = resolve_cft_platform()
    chrome_root = tmp_path / ".slug" / "browser" / plat / "chrome"
    driver_root = tmp_path / ".slug" / "browser" / plat / "chromedriver"
    cbin = chrome_executable_path_after_extract(plat, chrome_root)
    dbin = chromedriver_executable_path_after_extract(plat, driver_root)
    cbin.parent.mkdir(parents=True, exist_ok=True)
    dbin.parent.mkdir(parents=True, exist_ok=True)
    cbin.write_bytes(b"")
    dbin.write_bytes(b"")

    monkeypatch.setenv("CHROME_BIN", "/env/chrome")
    monkeypatch.setenv("CHROMEDRIVER_BIN", "/env/driver")

    backend = SeleniumBackend.__new__(SeleniumBackend)
    backend.config = SimpleNamespace(
        main=SimpleNamespace(
            use_docker=False,
            chrome_binary_path=None,
            chromedriver_binary_path=None,
        )
    )
    chrome, driver = backend._resolve_browser_binaries()
    assert chrome == "/env/chrome"
    assert driver == "/env/driver"


def test_read_bundled_sample_config():
    from igscraper.bootstrap import read_bundled_sample_config_text

    text = read_bundled_sample_config_text()
    assert "[main]" in text
    assert "thor_worker_id" in text
