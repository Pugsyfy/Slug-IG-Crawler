# Logging Configuration Audit & Fixes

## Overview

All logging throughout igscraper now properly derives settings from `config.toml [logging]` section and respects them. This ensures consistent logging behavior across the entire codebase.

## Changes Made

### 1. Fixed `logger.py`
- **Removed duplicate imports** (lines 1-10 and 13-16 were duplicated)
- **Enhanced documentation** in `get_logger()` to clarify it respects `config.toml`
- **Clarified comments** for third-party library logger suppressions (these are library-specific, not app-level)

### 2. Fixed `config.py`
- **Added clarifying comments** for third-party library logger suppressions
- **Documented** that these settings are independent of `config.toml [logging]` section

### 3. Replaced Direct `logging.getLogger()` with `get_logger()`

All application code now uses `get_logger()` which respects `config.toml`:

| File | Change |
|------|--------|
| `services/enqueue_client.py` | `logging.getLogger(__name__)` → `get_logger(__name__)` |
| `utils/video_finalizer.py` | `logging.getLogger(__name__)` → `get_logger(__name__)` |
| `services/upload_enqueue.py` | `logging.getLogger(__name__)` → `get_logger(__name__)` |
| `services/sorter.py` | `logging.getLogger(__name__)` → `get_logger(__name__)` |
| `models/common.py` | Removed duplicate logger definitions, unified to `get_logger(__name__)` |
| `services/replies_expander.py` | Fallback changed from `logging.getLogger(__name__)` → `get_logger(__name__)` |
| `decorator.py` | Fallback changed from `logging.getLogger(func.__module__)` → `get_logger(func.__module__)` |

## How Logging Works

### Configuration Flow

1. **Config Loading** (`config.py::load_config()`):
   ```python
   data = toml.load(path)  # Load config.toml
   configure_root_logger(data)  # Configure root logger from [logging] section
   ```

2. **Root Logger Configuration** (`logger.py::configure_root_logger()`):
   - Reads `[logging]` section from config dict
   - Sets root logger level from `level` field
   - Creates console handler with `log_format` and `date_format`
   - Creates file handler with logs in `log_dir`
   - All handlers use the same formatter from config

3. **Application Loggers** (`logger.py::get_logger()`):
   - Returns child loggers via `logging.getLogger(name)`
   - Child loggers inherit root logger's level, handlers, and formatters
   - All application code uses `get_logger(__name__)` to get loggers

### Config.toml Structure

```toml
[logging]
level = "DEBUG"  # Controls all application loggers
log_dir = "outputs/logs"
log_format = "%(asctime)s [%(levelname)s/%(processName)s] %(name)s: %(message)s"
date_format = "%Y-%m-%d %H:%M:%S"
```

### Third-Party Library Loggers

Some third-party libraries are explicitly silenced (these are **independent** of `config.toml`):

- `seleniumwire.*` → WARNING
- `h2`, `hpack` → WARNING
- `selenium` → WARNING
- `urllib3` → ERROR
- `webdriver_manager`, `WDM` → ERROR
- `selenium.webdriver.remote` → INFO

These settings are **library-specific** and only affect external library noise, not application logging.

## Verification

### ✅ All Application Loggers Use `get_logger()`

**Files using `get_logger()`:**
- `pipeline.py`
- `backends/selenium_backend.py`
- `config.py`
- `utils.py`
- `pages/profile_page.py`
- `services/full_media_download_script.py`
- `models/registry_parser.py`
- `downloader.py`
- `services/enqueue_client.py` ✅ **Fixed**
- `utils/video_finalizer.py` ✅ **Fixed**
- `services/upload_enqueue.py` ✅ **Fixed**
- `services/sorter.py` ✅ **Fixed**
- `models/common.py` ✅ **Fixed**
- `services/replies_expander.py` ✅ **Fixed**
- `decorator.py` ✅ **Fixed**

### ✅ Remaining `logging.getLogger()` Uses Are Appropriate

**Only used for:**
1. Third-party library loggers (silencing noise)
2. Root logger implementation in `logger.py` itself

## Benefits

✅ **Consistent Logging**: All application loggers respect `config.toml [logging]` settings
✅ **Centralized Configuration**: Change log level/format in one place (`config.toml`)
✅ **Proper Inheritance**: Child loggers inherit root logger settings automatically
✅ **No Breaking Changes**: All changes are surgical and backward compatible
✅ **Clear Separation**: Third-party library suppressions are clearly documented

## Testing

To verify logging respects config:

1. **Set log level in config.toml:**
   ```toml
   [logging]
   level = "DEBUG"
   ```

2. **Run igscraper:**
   ```bash
   python -m igscraper.cli --config config.toml
   ```

3. **Verify:**
   - Console output uses format from `log_format`
   - Log file created in `log_dir` with same format
   - DEBUG messages appear (if level=DEBUG)
   - All loggers use consistent formatting

## Files Changed

1. `src/igscraper/logger.py` - Fixed duplicates, enhanced docs
2. `src/igscraper/config.py` - Added clarifying comments
3. `src/igscraper/services/enqueue_client.py` - Use `get_logger()`
4. `src/igscraper/utils/video_finalizer.py` - Use `get_logger()`
5. `src/igscraper/services/upload_enqueue.py` - Use `get_logger()`
6. `src/igscraper/services/sorter.py` - Use `get_logger()`
7. `src/igscraper/models/common.py` - Unified to `get_logger()`
8. `src/igscraper/services/replies_expander.py` - Use `get_logger()` in fallback
9. `src/igscraper/decorator.py` - Use `get_logger()` in fallback

## Summary

All logging throughout igscraper now properly derives from `config.toml [logging]` section. All application code uses `get_logger()` which returns loggers that inherit root logger settings. Third-party library suppressions are clearly separated and documented.
