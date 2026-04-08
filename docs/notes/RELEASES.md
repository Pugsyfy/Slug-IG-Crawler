# Release Notes

## v2.1.0 - 2026-01-25

### ✨ Features

#### Worker Integration & Orchestration
- **Thor Worker ID Propagation**: Full integration with Thor orchestrator system
  - Added `thor_worker_id` propagation through igscraper runtime
  - Worker ID prefix added to screenshot video filenames for better traceability
  - Chrome profile moved to `/tmp` with worker_id and random suffix for isolation
  - Fixed worker ID issues and improved worker cookie management

#### Screenshot & Video System
- **Screenshot-to-Video Finalization**: Production-grade screenshot capture and video generation
  - Automatic MP4 video generation from screenshots at shutdown (2.5 FPS, 640p height)
  - GCS upload integration for video artifacts (`gs://{bucket}/vid_log/{video_name}.mp4`)
  - Automatic cleanup of local screenshots and video files after upload
  - Worker ID prefix in video filenames for better organization
  - Bucket name validation and sanitization (handles path-like values, removes `gs://` prefix)
  - Works for both PROFILE (mode 1) and POST (mode 2) jobs

#### Performance & Observability
- **Production-Grade Timing Logs**: Comprehensive performance tracking
  - Active time tracking (intentional work time, excludes sleeps/backoff)
  - Total time tracking (end-to-end wall time, includes all waits)
  - Structured JSON logs for Prometheus/Loki ingestion
  - Profile-level and post-level timing metrics
  - Error tracking with exception types in timing logs

#### Docker & Infrastructure
- **Production-Grade Docker Support**: Enhanced containerization
  - Production-grade Docker and Docker Compose v2 installation script
  - Environment variable-based configuration with `.env.example`
  - Improved Docker Compose configuration with proper volume mounts
  - Chrome profile isolation with worker_id-based directories
  - Tmpfs size optimization (1G) for better performance
  - Debug attachment flag management

#### Comment Extraction Improvements
- **Enhanced Comment Extraction**: More robust comment collection
  - Configurable `comment_no_new_retries` parameter for comment extraction control
  - Changed max_comments override matching from URL-based to shortcode-based (more reliable)
  - Added retry logic and wait conditions for comment container discovery
  - Improved error handling and recovery

#### Logging & Debugging
- **Improved Logging**: Better observability and debugging
  - Password redaction in logs for security
  - Demoted verbose logs to DEBUG level (URL file contents, mode 2 details)
  - Added INFO logs for URL file contents in mode 2 for debugging
  - Added current/total progress indicator for mode 1 profile scrapes
  - Better log level management throughout the codebase

#### Configuration & Pipeline
- **Pipeline Improvements**: Enhanced scraping pipeline
  - Pipeline and configuration refactoring for better maintainability
  - Updated Postgres config defaults for enqueue client
  - Deferred trace validation to Pipeline.init to avoid celery import failures
  - Environment validation script for ig_profile_scraper
  - Base config additions

#### Documentation
- **Comprehensive Documentation**: Updated and expanded documentation
  - Complete README rewrite with Docker support documentation
  - Mode 2 URL file logging and path analysis documentation
  - Production-grade documentation for all new features

### 🔧 Improvements

- **Chrome Profile Management**: Moved Chrome profile to `/tmp` with worker_id and random suffix for better isolation
- **Docker Configuration**: Improved docker-compose.yml with environment variables and better resource management
- **Error Handling**: Better error handling and recovery mechanisms throughout
- **Code Quality**: Refactoring and improvements to pipeline and configuration management

### 🐛 Bug Fixes

- Fixed worker ID propagation issues
- Fixed Postgres config defaults for enqueue client
- Fixed trace validation to avoid celery import failures
- Fixed max_comments override matching (changed from URL to shortcode)
- Fixed comment container discovery with retry logic

### 📝 Technical Details

- **Video Generation**: Uses imageio and imageio-ffmpeg for MP4 generation
- **GCS Integration**: Automatic upload to configured GCS bucket with proper path sanitization
- **Timing Metrics**: Uses `time.perf_counter()` for precise measurements
- **Worker Isolation**: Each worker gets isolated Chrome profile directory

### 🔄 Migration Notes

- **Configuration**: New `comment_no_new_retries` parameter available in config
- **Environment Variables**: Updated `.env.example` with new variables
- **Docker**: Updated docker-compose.yml requires environment variables
- **Worker ID**: Now requires `thor_worker_id` in config `[trace]` section

---

## v2.0.1 - Previous Release

[Previous release notes would go here]

---

## v1.0.0 - Initial Release

This is the first public release of the Instagram Profile Scraper. This version provides the core functionality for authenticating, configuring, and scraping posts from a public Instagram profile.

### ✨ Features

- **Cookie-Based Authentication**: Log in securely using browser cookies to mimic a real user session and reduce the risk of detection.
- **Configurable Scraping**: Use a simple `config.toml` file to specify the target profile, number of posts, and other scraping parameters.
- **Batch Processing**: Scrapes posts in configurable batches, opening each post in a new tab to ensure a stable and robust process.
- **Data Extraction**: Capable of extracting key metadata from posts, including:
  - Post caption and timestamp.
  - Like counts.
  - Comments, including text, commenter handle, and associated GIFs.
  - Images from single-image posts.
- **Human-Like Behavior**: Incorporates random delays and simulated mouse movements to better emulate human browsing patterns.
- **Resumability & Caching**: Caches collected post URLs and checks against already scraped data, allowing the scraper to resume without re-processing completed posts.
- **Structured Output**: Saves scraped data in easy-to-parse JSONL format and logs skipped posts for review.
- **File-based Logging**: In addition to console output, all logs are saved to a timestamped `scraper_log_{timestamp}.log` file in the root directory.

### ⚠️ Known Issues

- **Reels Not Supported**: The scraper is currently configured to collect and process only standard image/carousel posts. Instagram Reels are intentionally skipped.
- **Carousel Image Scraping**: The current implementation for scraping multi-image (carousel) posts is not fully functional. While it successfully scrapes images from single-image posts, it may fail to retrieve all images from a carousel.
- **Code Refinements Needed**: The codebase contains some experimental and legacy functions that have been commented out. This code is pending review and cleanup.
- **Selector Fragility**: While data extraction for key areas like comments, post titles, and images uses robust, structure-based heuristics, other parts of the scraper rely on specific CSS selectors. These are tied to Instagram's current HTML and may require updates if the website's structure changes significantly.

### 🚀 Future Improvements

- **Improve Carousel Scraping**: The top priority is to implement a reliable method for extracting all images from carousel posts.
- **Code Refactoring**: Clean up the codebase by removing commented-out sections and improving modularity. For instance, the large `scrape_posts_in_batches` function could be broken down into smaller, more manageable pieces.
- **Externalize JavaScript**: Move large, inline JavaScript snippets from Python files into separate `.js` files to improve readability and maintainability.

---

Thank you for trying out this initial release! Feedback and contributions are welcome.