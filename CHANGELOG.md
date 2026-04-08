# Changelog

All notable changes to this project are documented in this file.

## [2.2.23] - 2026-04-08

### Changed
- Improved terminal CLI UX:
  - top-level `Slug-Ig-Crawler --help` now shows a clear command list and guidance
  - running with no args now prints help instead of implicitly running
  - invalid commands now print clearer errors with command hints
  - per-command help is consistently available via `Slug-Ig-Crawler <command> --help`
- Made `bootstrap` output more verbose with explicit progress and cache details.
- Reduced non-run command noise by lazy-loading runtime-heavy imports for CLI run path.

## [2.2.22] - 2026-04-08

### Added
- CLI command `Slug-Ig-Crawler version` to print the installed package version.
- CLI command `Slug-Ig-Crawler list-cookies` to print only cookie JSON paths from `~/.slug/cookies`.

### Changed
- `Slug-Ig-Crawler show-config` now also lists discovered TOML config files under the cache folder and cookie JSON files with absolute paths.
- README command documentation updated to include `version`, `list-cookies`, and enhanced `show-config` behavior.

## [2.2.21] - 2026-04-08

### Added
- CLI command `Slug-Ig-Crawler save-cookie --username <instagram_username>` to capture Instagram login cookies without running a scrape.
- Cookie cache helpers for `~/.slug/cookies`, including stable pointer `~/.slug/cookies/latest.json`.
- Cookie filename format enforcement: `<browserVersion>_<username>_<timestamp>.json`.
- Tests for cookie cache path helpers, `~` path expansion, and cookie filename formatting.

### Changed
- Refactored cookie capture logic into callable module functions used by the CLI.
- Cookie capture binary resolution now follows existing cache/env conventions:
  - `CHROME_BIN`/`CHROMEDRIVER_BIN`
  - cached bootstrap pair in `~/.slug/browser/...`
  - Selenium/system fallback
- Sample config defaults now point `cookie_file` to `~/.slug/cookies/latest.json`.
- README updated for `save-cookie` usage and cookie path guidance.
- Config path resolver now expands `~` so cached cookie paths resolve correctly.

