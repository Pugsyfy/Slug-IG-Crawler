# Full Workflow Explained

This document describes the end-to-end scraping workflow for the Instagram profile scraper. The process is orchestrated via a command-line interface and follows a modular pipeline, leveraging Selenium for browser automation and JavaScript injection for efficient data extraction.

---

## 1. Initialization & Environment Setup

- **Start Command:**  
    The primary entry point is the `run_scraper.sh` script.
    ```bash
    ./run_scraper.sh
    ```
- **Script Workflow:**
    1.  **Environment Setup:** Activates the Python virtual environment and sets the `PYTHONPATH`.
    2.  **Redis Check:** Checks if a Redis server is running. If not, it attempts to start one using `brew` or `docker`. Redis is used as the Celery message broker for background tasks.
    3.  **Celery Worker:** Checks if a Celery worker is already running. If not, it starts one in the background. The worker's role is to handle asynchronous tasks, specifically video downloads, offloading them from the main scraping process.
    4.  **Scraper Execution:** Executes the main Python scraper script:
        ```bash
        python -m igscraper.cli --config config.toml
        ```
- **Python Application Initialization:**
    - The `main()` function in `cli.py` is called, which parses arguments and instantiates the `Pipeline` class.
    - The `Pipeline` class loads and validates `config.toml` using Pydantic models from `config.py`.
    - It then initializes the `SeleniumBackend`.

---

## 2. Browser Start-up & Login

- `Pipeline.run()` calls `self.backend.start()`.
- `SeleniumBackend.start()`:
    - Configures and launches Chrome with anti-detection settings (e.g., disables automation flags, sets user-agent).
    - Navigates to `instagram.com`.
    - Authenticates using cookies from the config (`_login_with_cookies`), bypassing manual login.

---

## 3. Target Selection & URL Collection

- **Modes:**
    - **Profile Mode:** Scrapes a list of profiles.
    - **URL File Mode:** Scrapes a predefined list of post URLs.

### Profile Mode Workflow

1. Iterate through each `target_profile` in config.
2. For each profile:
     - `backend.open_profile()` navigates to the profile page.
     - `backend.get_post_elements()`:
         - Checks for cached post URLs (`posts_{target_profile}.txt`).
         - If no cache, calls `ProfilePage.scroll_and_collect_()` to simulate scrolling and collect post URLs up to the configured limit.
         - Saves URLs to cache.
     - Filters out already-scraped URLs by checking `metadata_{target_profile}.jsonl`.

---

## 4. Batch Scraping

- Passes URLs to `backend.scrape_posts_in_batches()`.
- Opens `batch_size` posts in new browser tabs (`window.open()`).
- Iterates through tabs to scrape content.

---

## 5. Single Post Scraping

- `_scrape_and_close_tab()` in `SeleniumBackend`:
    - Switches to post tab.
    - Extracts data (each step wrapped in `try...except`):
        - **Title/Caption:** `get_post_title_data()`
        - **Media:** `media_from_post_gpt()` (handles images, carousels, videos; uses network requests for downloadable videos)
        - **Video Downloads:** Dispatches Celery task (`write_and_run_full_download_script_`)
        - **Likes:** `get_section_with_highest_likes()`
        - **Comments:** `scrape_comments_with_gif()` (scrolls comment container, injects JS to parse comments and GIFs)
    - Closes tab and returns focus to main window.

---

## 6. Saving Results & Teardown

- After each post:
    - Appends data to temp file (`scrape_results_tmp_{...}.jsonl`) via `save_intermediate()`.
- After every `save_every` posts:
    - Moves data to final output files (`metadata_{...}.jsonl`, `skipped_{...}.txt`).
    - Clears temp file.
- After all batches:
    - `Pipeline.run()` calls `backend.stop()` to quit browser and close WebDriver.

---

## Main Modules, Classes, and Functions

| Module/Class | Responsibility |
|--------------|---------------|
| `igscraper.cli` | CLI entry point; parses arguments |
| `igscraper.pipeline.Pipeline` | Orchestrates workflow; manages backend and targets |
| `igscraper.config` | Pydantic models for config; path expansion |
| `igscraper.backends.selenium_backend.SeleniumBackend` | Core scraping logic; browser actions; data extraction loop |
| `igscraper.pages.profile_page.ProfilePage` | Page Object Model for profile page; scrolling and URL collection |
| `igscraper.utils` | Helper functions (data extraction, human simulation, persistence) |
| `igscraper.logger` | Logging to console and file |

**Key Functions:**
- Data Extraction: `get_post_title_data`, `media_from_post_gpt`, `scrape_comments_with_gif`
- Human Simulation: `human_scroll`, `human_mouse_move`, `random_delay`
- Data Persistence: `save_scrape_results`, `save_intermediate`

---

## Python, Selenium, and JavaScript Interaction

- **Python:** Orchestrates logic, configuration, file handling.
- **Selenium:** Automates browser actions (navigation, clicking, tab management).
- **JavaScript:** Injected via `driver.execute_script()` for fast, robust DOM traversal and data extraction.

**Benefits:**
- Efficient DOM parsing.
- Handles complex/nested structures in one operation.
- Accesses browser APIs (e.g., `performance.getEntriesByType("resource")` for video URLs).

---

## Assumptions in Scraping Logic

- **DOM Structure:** Relies on current HTML/CSS selectors (fragile to Instagram updates).
- **Infinite Scroll:** Assumes new content loads on scroll; detects end by unchanged `scrollHeight`.
- **Post URLs:** Assumes `/p/` or `/reel/` patterns.
- **Network Requests:** Assumes `.mp4` URLs are available in performance logs.
- **Authentication:** Assumes cookies are sufficient for session; manual intervention may be needed.

---

## Error Handling, Retries, and Logging

- **Error Handling:**  
    - Broad `try...except` blocks prevent crashes.
    - Skipped posts logged with reasons.
- **Retries:**  
    - Scrolling and tab opening have retry mechanisms for robustness.
- **Logging:**  
    - Logs to console and file (`scraper_log_{timestamp}.log`).
    - Tracks progress, warnings, errors.
    - Exception messages at ERROR level; full tracebacks at DEBUG level.

---