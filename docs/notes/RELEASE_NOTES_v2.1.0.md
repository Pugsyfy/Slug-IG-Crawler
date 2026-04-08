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
