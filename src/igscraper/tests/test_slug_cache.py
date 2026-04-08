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
    get_cached_dotenv_path,
    get_cookie_cache_dir,
    get_latest_cookie_path,
    resolve_cft_platform,
)


def test_resolve_cft_platform_linux_or_mac():
    plat = resolve_cft_platform()
    assert plat in ("linux64", "mac-arm64", "mac-x64")


def test_cached_config_path_respects_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert get_cached_config_path() == tmp_path / ".slug" / "config.toml"


def test_cached_dotenv_path_respects_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert get_cached_dotenv_path() == tmp_path / ".slug" / ".env"


def test_get_cached_browser_binaries_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    c, d = get_cached_browser_binaries()
    assert c is None and d is None


def test_cookie_cache_paths_respect_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert get_cookie_cache_dir() == tmp_path / ".slug" / "cookies"
    assert get_latest_cookie_path() == tmp_path / ".slug" / "cookies" / "latest.json"


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


def test_resolve_path_expands_user_home(monkeypatch, tmp_path):
    from igscraper.config import resolve_path

    monkeypatch.setenv("HOME", str(tmp_path))
    out = resolve_path("~/.slug/cookies/latest.json")
    assert out == (tmp_path / ".slug" / "cookies" / "latest.json").resolve()


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


def test_cookie_filename_format():
    from igscraper.login_Save_cookie import _build_cookie_filename

    filename = _build_cookie_filename("143.0.7499.170", "user.name", 1700000000)
    assert filename == "143.0.7499.170_user.name_1700000000.json"


def test_list_cache_config_paths(monkeypatch, tmp_path):
    from igscraper import cli

    monkeypatch.setenv("HOME", str(tmp_path))
    root = tmp_path / ".slug"
    (root / "config.toml").parent.mkdir(parents=True, exist_ok=True)
    (root / "config.toml").write_text("[main]\nmode=1\n", encoding="utf-8")
    (root / "nested").mkdir(parents=True, exist_ok=True)
    (root / "nested" / "a.toml").write_text("x=1\n", encoding="utf-8")
    paths = cli._list_cache_config_paths()
    assert (root / "config.toml").resolve() in paths
    assert (root / "nested" / "a.toml").resolve() in paths


def test_list_cookie_paths(monkeypatch, tmp_path):
    from igscraper import cli

    monkeypatch.setenv("HOME", str(tmp_path))
    cookie_dir = tmp_path / ".slug" / "cookies"
    cookie_dir.mkdir(parents=True, exist_ok=True)
    (cookie_dir / "latest.json").write_text("[]", encoding="utf-8")
    (cookie_dir / "a.json").write_text("[]", encoding="utf-8")
    (cookie_dir / "ignore.txt").write_text("x", encoding="utf-8")
    paths = cli._list_cookie_paths()
    assert (cookie_dir / "latest.json").resolve() in paths
    assert (cookie_dir / "a.json").resolve() in paths
    assert all(p.suffix == ".json" for p in paths)
