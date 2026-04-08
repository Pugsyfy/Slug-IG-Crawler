# Per-Post `max_comments` Override Feature

## Overview

This feature enables **per-post control of `max_comments`** when scraping Instagram posts using Mode 2 (URL file mode). Each post URL can now specify its own `max_comments` value, allowing fine-grained control over comment scraping depth.

## URL File Format

### Legacy Format (Backward Compatible)
```
https://www.instagram.com/p/POST_ID_1/
https://www.instagram.com/p/POST_ID_2/
```
→ Uses default `max_comments` from `config.toml`

### Extended Format (New)
```
https://www.instagram.com/p/POST_ID_1/|max_comments=50
https://www.instagram.com/p/POST_ID_2/|max_comments=100
```
→ Overrides `max_comments` to 50 and 100 respectively

### Mixed Format (Supported)
```
https://www.instagram.com/p/POST_ID_1/
https://www.instagram.com/p/POST_ID_2/|max_comments=75
https://www.instagram.com/p/POST_ID_3/
```
→ POST_ID_1 and POST_ID_3 use default, POST_ID_2 uses 75

## Implementation Details

### 1. URL File Parsing (`pipeline.py`)
- Reads URL file line by line
- Splits on `|` to extract URL and metadata
- Parses `key=value` pairs
- Validates `max_comments` (must be positive integer)
- Stores metadata in `url_metadata` dict: `{url: {"max_comments": N}}`

### 2. Per-Tab Override (`selenium_backend.py`)
- Before scraping each tab, checks if URL has metadata override
- Temporarily sets `self.config.main.max_comments` to override value
- Calls `_scrape_and_close_tab()` (existing code path)
- **Always restores** original `max_comments` in `finally` block (exception-safe)

### 3. Thor Worker Integration (`igscraper_worker.py`)
- For POST jobs, generates URLs with `|max_comments=N` suffix
- Uses `job_params['num_posts']` as `max_comments` value
- Format: `https://www.instagram.com/p/{post_id}/|max_comments={num_posts}`

## Edge Cases Handled

✅ Invalid `max_comments` values (non-integer, negative, zero)
✅ Malformed metadata syntax
✅ Exceptions during scraping (guaranteed restoration via `finally`)
✅ Whitespace in metadata
✅ Missing `job_params['num_posts']` (defaults to 60)

## Benefits Delivered

✅ **Surgical** - Only 3 files changed, 5 touchpoints
✅ **Per-shortcode control** - Each post can have different `max_comments`
✅ **Backward compatible** - Old URL files continue to work
✅ **Exception-safe** - `finally` block guarantees restoration
✅ **Validated** - Input validation with graceful fallback
✅ **Observable** - Comprehensive logging at all stages

## Files Changed

1. `ig_profile_scraper/src/igscraper/pipeline.py` - URL metadata parsing
2. `ig_profile_scraper/src/igscraper/backends/selenium_backend.py` - Per-tab override
3. `thor/src/thor/workers/igscraper_worker.py` - Extended URL generation
