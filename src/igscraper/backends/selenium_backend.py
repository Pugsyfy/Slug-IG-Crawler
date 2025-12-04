import os
from pathlib import Path
from re import I
import sys
import time
import json
import pickle
import random
import traceback
from typing import Iterator, Dict, List, Any

from selenium import webdriver
from seleniumwire import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
from webdriver_manager.chrome import ChromeDriverManager

from igscraper.services.replies_expander import ReplyExpander

from .base_backend import Backend
from ..pages.profile_page import ProfilePage
from ..logger import get_logger

from igscraper.chrome import patch_driver
from igscraper.utils import (
    click_all_reply_buttons_gently,
    extract_script_embedded_comments,
    find_comment_container,
    human_mouse_move,
    media_from_post,
    get_section_with_highest_likes,
    scrape_comments_with_gif,
    save_intermediate,
    save_scrape_results,
    clear_tmp_file,
    random_delay,
    get_top_mp4_groups_with_curl,
    robust_mouse_move,
    media_from_post_gpt,
    find_audio_for_videos,
    unmute_reel,
    set_reel_volume,
    write_and_run_curl_script,
    write_and_run_full_download_script,
    get_shortcode_web_info,
    list_logged_urls,
    get_first_link_href_base,
    classify_mp4_files,
    unmute_if_muted
)
from igscraper.mycelery.tasks import write_and_run_full_download_script_
from igscraper.services.enqueue_client import PostgresConfig, FileEnqueuer
from igscraper.services.upload_enqueue import GcsUploadConfig, UploadAndEnqueue

import pdb


logger = get_logger(__name__)

class SeleniumBackend(Backend):
    """
    A backend implementation using Selenium to control a web browser for scraping.

    This class manages the browser lifecycle, navigation, and data extraction
    by interacting with web pages and executing JavaScript.
    """
    def __init__(self, config):
        """
        Initializes the SeleniumBackend.

        Args:
            config: The application's configuration object.
        """
        self.config = config
        self.driver = None
        self.profile_page = None
        self.reply_expander = None
        self.rate_limit_detected = False
        self.rate_limit_reset_time = 0
        self.rate_limit_attempts = 0 
        pg_cfg = PostgresConfig.from_env()
        enqueuer = FileEnqueuer(pg_cfg)
        gcs_cfg = GcsUploadConfig(bucket_name=self.config.main.gcs_bucket_name)
        self.uploader = UploadAndEnqueue(gcs_cfg, enqueuer)
        self._state_file = "rate_limit_state.json"  # persistent file
        self._load_rate_limit_state()


    def start(self):
        """
        Starts the Selenium WebDriver, configures it for stealth, and logs in.

        - Sets up Chrome options to evade bot detection.
        - Initializes the Chrome driver using webdriver-manager.
        - Patches the driver to monitor for suspicious navigation.
        - Logs in using cookies specified in the configuration.
        - Initializes the ProfilePage object for page interactions.
        """
        options = Options()
        caps = options.to_capabilities()
        # Only keep network events
        perf_log_prefs = {
            "enableNetwork": True
        }
        options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
        options.set_capability("goog:perfLoggingPrefs", perf_log_prefs)
        # caps = DesiredCapabilities.CHROME.copy()
        # caps['goog:loggingPrefs'] = {'performance': 'ALL'}
        # caps["goog:perfLoggingPrefs"] = perf_log_prefs

        # --- Anti-detection settings from test_sel.py ---
        options.add_argument("--disable-blink-features=AutomationControlled")
        # options.add_argument("--auto-open-devtools-for-tabs") # testing for dev UI tools
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        options.add_argument("--autoplay-policy=no-user-gesture-required")
        options.add_argument("--disable-background-timer-throttling")
        options.add_argument("--disable-renderer-backgrounding")
        options.add_argument("--disable-backgrounding-occluded-windows")
        # Human-like settings
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--start-maximized")

        # Use user_agent from config or a default one
        user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36"
        options.add_argument(f'user-agent={user_agent}')

        if self.config.main.headless:
            options.add_argument("--headless=new")

        # Use WebDriver Manager for automatic driver management
        try:
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=options)
            self.driver = patch_driver(self.driver)
        except Exception as e:
            logger.error(f"Failed to initialize Chrome driver with webdriver-manager: {e}")
            logger.info("Falling back to default webdriver initialization.")
            self.driver = webdriver.Chrome(options=options)
            ## Patch driver to stop the script if detection happens and we are rerouted to a captcha page
            self.driver = patch_driver(self.driver)

        self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        self.setup_network()
        self._login_with_cookies()
        self.profile_page = ProfilePage(self.driver, self.config)

    def setup_network(self):
        # Enable network tracking
        self.driver.execute_cdp_cmd("Network.enable", {})
        self.driver.execute_cdp_cmd("Network.clearBrowserCache", {})
        self.driver.execute_cdp_cmd("Network.clearBrowserCookies", {})
        self.driver.set_script_timeout(180)
        self.driver.command_executor.set_timeout(300) 

    def _login_with_cookies(self):
        """
        Loads cookies from a file to authenticate the browser session.

        The browser must first navigate to the domain ('instagram.com') before
        cookies can be added. The path to the cookie file is read from the
        configuration. If the file doesn't exist, the program will exit.
        """
        if not self.config.data.cookie_file or not os.path.exists(self.config.data.cookie_file):
            logger.info("No cookie file specified in config or cookie file does not exist. Exiting early.")
            sys.exit(1)

        logger.info(f"Attempting to log in using cookies from {self.config.data.cookie_file}")
        self.driver.get("https://www.instagram.com/")  # Must visit domain first

        try:
            with open(self.config.data.cookie_file, "rb") as f:
                cookies = pickle.load(f)
        except (pickle.UnpicklingError, EOFError) as e:
            logger.error(f"Could not load cookies from {self.config.data.cookie_file}. Error: {e}")
            return

        for cookie in cookies:
            # Selenium expects 'expiry' to be int if present
            if 'expiry' in cookie and isinstance(cookie['expiry'], float):
                cookie['expiry'] = int(cookie['expiry'])
            self.driver.add_cookie(cookie)

        self.driver.refresh()  # Apply cookies
        logger.info("✅ Successfully logged in using cookies.")
        time.sleep(3) # Wait a bit for page to settle

    def stop(self):
        """Quits the WebDriver and closes all associated browser windows."""
        if self.driver:
            self.driver.quit()

    def open_profile(self, profile_handle: str) -> None:
        """
        Navigates the browser to a specific Instagram profile page.

        Args:
            profile_handle: The Instagram username of the profile to open.
        """
        self.profile_page.navigate_to_profile(profile_handle)

    def _load_cached_urls(self, file_path: str) -> list[str] | None:
        """
        Loads a list of post URLs from a local JSON file if it exists.

        Args:
            file_path: The path to the JSON file containing post URLs.

        Returns:
            A list of URL strings if the file is found and loaded, otherwise None.
        """
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                urls = json.load(f)
            logger.info(f"Loaded {len(urls)} post URLs from {file_path}.")
            return urls
        return None

    def _save_urls(self, profile: str, urls: list[str], file_path: str) -> None:
        """
        Saves a list of post URLs to a local JSON file.

        Args:
            profile: The target profile name (used for logging).
            urls: A list of URL strings to save.
            file_path: The path where the JSON file will be saved.
        """
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(urls, f, ensure_ascii=False, indent=2)
        logger.info(f"Saved {len(urls)} post URLs to {file_path}.")

    def _load_processed_urls(self, file_path: str) -> set[str]:
        """
        Loads URLs of already scraped posts from the output metadata file.

        This is used to avoid re-scraping posts that have already been processed
        in previous runs.

        Args:
            file_path: The path to the JSONL metadata output file.

        Returns:
            A set of post URL strings that have already been processed.
        """
        processed = set()
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        record = json.loads(line)
                        if "post_url" in record:
                            processed.add(record["post_url"])
                    except json.JSONDecodeError:
                        continue
            logger.info(f"Loaded {len(processed)} processed post URLs from {file_path}.")
        return processed

    def get_post_elements(self, limit: int) -> Iterator[Any]:
        """
        Retrieves a list of post URLs to be scraped for a given profile.

        This function implements a caching and filtering logic:
        1. It first tries to load post URLs from a cached file (`posts_path`).
        2. If no cache exists, it scrapes the profile page to collect the URLs and
           saves them to the cache file for future runs.
        3. It then loads the list of URLs that have already been processed from
           the final metadata output file.
        4. It filters the collected URLs, removing any that have already been processed.

        Args:
            limit: The maximum number of post URLs to collect if scraping from scratch.
        """
        profile = self.config.main.target_profile
        posts_path = self.config.data.posts_path

        # Load cached urls
        cached = self._load_cached_urls(posts_path)
        if cached is None:
            # Scrape fresh if no cache
            is_data_saved, elements = self.profile_page.scroll_and_collect_(limit)
            urls = [elem for elem in elements]
            self._save_urls(profile, urls, posts_path)
            if is_data_saved:
                logger.info("Posts data was saved during collection. Trying to push to gs bucket")
                self.on_posts_batch_ready(self.config.data.profile_path)
        else:
            urls = cached

        # Filter out already processed urls
        processed_data_path = self.config.data.metadata_path
        processed = self._load_processed_urls(processed_data_path)
        urls = [u for u in urls if u not in processed]

        logger.info(f"Returning {len(urls)} post URLs after filtering out {len(processed)} processed ones.")
        return urls


    def extract_comments(self, steps:int = None):
        """
        Extracts comments from the currently open post page.

        Args:
            steps: The number of scroll steps to perform while collecting comments.
                   If None, a default value is used.
        """
        return self.profile_page.extract_comments(steps=steps)

    def extract_post_metadata(self, post_element: Any) -> Dict:
        """
        Placeholder for extracting metadata from a post element.
        (Not yet implemented)
        """
        pass

    def _scrape_and_close_tab(self, post_index: int, post_url: str, tab_handle: str, main_window_handle: str, debug: bool) -> tuple[dict | None, dict | None]:
        """
        Scrapes a single post in its dedicated tab and then closes the tab.

        This method encapsulates the entire lifecycle for one post, including
        switching to the tab, data extraction with individual error handling,
        and robustly closing the tab and switching back to the main window.

        Args:
            post_index: The index of the post.
            post_url: The URL of the post.
            tab_handle: The window handle for the post's tab.
            main_window_handle: The window handle of the main tab.
            debug: If True, the tab will not be closed.

        Returns:
            A tuple containing (post_data, error_data).
            - (post_data, None) on success.
            - (None, error_dict) on failure.
            - (None, None) if no browser windows are left.
        """
        try:
            # switch to the new tab
            self.driver.switch_to.window(tab_handle)
            # unmute_if_muted(self.driver, 0.2)

            # del self.driver.requests  # Clear any previous requests to avoid memory bloat
            logger.info(f"Switched to tab {tab_handle} for post {post_index} ({post_url}). Refreshing page.")
            # self.driver.refresh()
            random_delay(2.4, 4.0)  # Wait for at least 3 seconds for the page to load after refresh.

            # Anti Bot measure
            if random.choice([0,0,1,1,1,1,1]) == 0:
                human_mouse_move(self.driver,duration=self.config.main.human_mouse_move_duration)

            post_id = f"post_{post_index}"
            post_data = {
                "post_url": post_url,
                "post_id": post_id,
                "post_title": None,
                "post_images": [],
                "post_comments_gif": [],
            }

            # If using previously-captured requests to gather most media/metadata,
            # we only need to extract comments here. Skip other extraction blocks.
            if self.config.main.scrape_using_captured_requests:
                logger.info(f"scrape_using_captured_requests=True — extracting comments only for {post_url}")
                try:
                    post_data["post_comments_gif"] = self._extract_comments_from_captured_requests(self.driver, self.config) or []
                    logger.info(f"Captured-requests comment extraction returned {len(post_data['post_comments_gif'])} items for {post_url}")
                except Exception as e:
                    logger.error(f"Captured-requests comment extraction failed for {post_url}: {e}")
                    logger.debug(traceback.format_exc())

                return post_data, None

            # Title / metadata
            try:
                handle_slug = ""
                if self.config.main.mode == 1:
                    handle_slug = f"/{self.config.main.target_profile}/"
                else:
                    handle_slug = get_first_link_href_base(self.driver)
                logger.info(f"Extracting title data for {post_url} with handle {handle_slug}")
                post_data["post_title"] = self.get_post_title_data(handle_slug) or ""
            except Exception as e:
                logger.error(f"Title extraction failed for {post_url}: {e}")
                logger.debug(traceback.format_exc())

            # Media: Extract media - videos/images
            try:
                # pdb.set_trace()
                # out = capture_graphql_queries(self.driver, 100000)
                # result = get_shortcode_web_info(self.driver)
                # pdb.set_trace()
                images_data, video_data_list, img_vid_map = media_from_post_gpt(self.driver)
                post_data["post_media"] = images_data
                # unmute_if_muted(self.driver, 0.2)
                # pdb.set_trace()
                if video_data_list:
                    post_data["video_download_tasks"] = []
                    task = write_and_run_full_download_script_.delay(video_data_list, self.config.data.media_path,out_script_path="download_full_media.sh",
                                    run_script=True, redact_cookies=True)
                    logger.info(f"Dispatched {len(video_data_list)} video download tasks.")
                    post_data["video_download_tasks"].append(task.id)

            except Exception as e:
                logger.error(f"Images extraction failed for {post_url}: {e}")
                logger.debug(traceback.format_exc())
            # Likes / other sections
            try:
                post_data["likes"] = get_section_with_highest_likes(self.driver) or {}
                logger.info(f"Likes extraction successful for {post_url}")
            except Exception as e:
                logger.error(f"Likes extraction failed for {post_url}: {e}")
                logger.debug(traceback.format_exc())
            
            # comments
            try:
                post_data["post_comments_gif"] = scrape_comments_with_gif(self.driver,self.config) or []
            except Exception as e:
                logger.error(f"Comments extraction with gif failed for {post_url}: {e}")
                logger.debug(traceback.format_exc())

            return post_data, None

        except Exception as e:
            logger.exception(f"Unexpected error while scraping post {post_index} ({post_url}): {e}")
            error_data = {"index": post_index, "reason": str(e), "profile": self.config.main.target_profile}
            return None, error_data
        finally:
            self._close_tab_and_switch_back(tab_handle, main_window_handle, debug)
            # Check if any windows are left open after closing.
            if not self.driver.window_handles:
                return None, None

    def scrape_posts_in_batches(self,
        post_elements,
        batch_size=3,
        save_every=5,
        tab_open_retries=4,
        debug=False
    ):
        """
        Scrapes a list of post URLs in batches, saving results periodically.

        This method iterates through the provided post URLs, opening each one in a
        new browser tab to scrape its content. It is designed to be robust,
        handling tab management, data extraction, and intermittent saving to
        prevent data loss.

        Args:
            post_elements (list[str]): A list of post URLs to scrape.
            batch_size (int): The number of posts to open in tabs at a time.
            save_every (int): The number of posts to scrape before saving the
                              collected data to the output files.
            tab_open_retries (int): The number of retries for detecting a new tab.
            debug (bool): If True, scraped tabs will not be closed, which is useful
                          for debugging.

        Returns:
            A dictionary containing lists of 'scraped_posts' and 'skipped_posts'.
        """
        results = {"scraped_posts": [], "skipped_posts": []}
        total_scraped = 0

        main_handle = self.driver.current_window_handle
        tmp_file = self.config.data.tmp_path

        # main loop over batches
        for batch_start in range(0, len(post_elements), batch_size):
            batch = post_elements[batch_start: batch_start + batch_size]
            opened = []  # list of tuples (index, href, handle)

            # --- open all posts in batch (in new tabs) ---
            for i, post_element in enumerate(batch, start=batch_start):
                try:
                    # href = post_element.get_attribute("href")
                    href = post_element
                    if not href:
                        logger.warning(
                            f"Skipping post {i+1} from profile {self.config.target_profile}: missing href."
                        )
                        results["skipped_posts"].append({
                            "index": i,
                            "reason": "missing href",
                            "profile": self.config.target_profile
                        })
                        continue

                    try:
                        new_handle = self.open_href_in_new_tab(href, tab_open_retries)
                        # optionally give the new tab a moment to start loading
                        time.sleep(random.uniform(0.8, 1.5))
                        opened.append((i, href, new_handle))
                        logger.info(f"Opened post {i+1} in new tab: {href} -> handle {new_handle}")
                    except Exception as e:
                        logger.error(f"Failed to open new tab for post {i+1}: {e}")
                        results["skipped_posts"].append({
                            "index": i,
                            "reason": f"failed to open tab: {str(e)}",
                            "profile": self.config.target_profile
                        })
                except Exception as e:
                    logger.exception(f"Unexpected error when preparing post {i+1}: {e}")
                    results["skipped_posts"].append({
                        "index": i,
                        "reason": f"error extracting href: {str(e)}",
                        "profile": self.config.target_profile
                    })

            # --- scrape each opened tab, one-by-one, ensuring closure ---
            for post_index, post_url, tab_handle in opened:
                post_data, error_data = self._scrape_and_close_tab(post_index, post_url, tab_handle, main_handle, debug)

                if post_data is None and error_data is None:
                    # This indicates no browser windows are left.
                    logger.info("No browser windows left after closing tab. Ending scrape.")
                    return results

                if error_data:
                    results["skipped_posts"].append(error_data)
                    continue

                if post_data:
                    results["scraped_posts"].append(post_data)
                    total_scraped += 1
                    logger.info(f"Scraped post {post_index} ({post_url}). Total scraped: {total_scraped}")

                    try:
                        save_intermediate(post_data, tmp_file)
                    except Exception as e:
                        logger.warning(f"Failed to write tmp result for {post_url}: {e}")

                    if total_scraped > 0 and total_scraped % save_every == 0:
                        save_scrape_results(results, self.config.data.output_dir, self.config)
                        clear_tmp_file(tmp_file)
                        logger.info(f"Saved results after {total_scraped} scraped posts.")

            # optional: jittered wait between batches to mimic human rate-limits
            random_delay(self.config.main.rate_limit_seconds_min, self.config.main.rate_limit_seconds_max)

        # final save
        if results["scraped_posts"] or results["skipped_posts"]:
            save_scrape_results(results, self.config.data.output_dir, self.config)
            # self.on_comments_batch_ready(self.config.data.metadata_path)
            clear_tmp_file(tmp_file)
            logger.info("Saved final scrape results.")

        return results

    def _close_tab_and_switch_back(self, tab_handle_to_close: str, main_window_handle: str, debug: bool):
        """
        Closes the specified tab and switches the driver's focus back.

        Args:
            tab_handle_to_close: The window handle of the tab to close.
            main_window_handle: The handle of the main window to switch back to.
            debug: If True, the tab will not be closed.
        """
        try:
            if debug:
                logger.info(f"DEBUG mode: leaving tab {tab_handle_to_close} open.")
            else:
                self.driver.close()
                logger.debug(f"Closed tab {tab_handle_to_close}")
        except Exception as e:
            logger.warning(f"Error closing tab {tab_handle_to_close}: {e}")

        handles = self.driver.window_handles
        if main_window_handle in handles:
            self.driver.switch_to.window(main_window_handle)
        elif handles:
            self.driver.switch_to.window(handles[0])
        logger.debug(f"Switched back to handle {self.driver.current_window_handle}")

    def open_href_in_new_tab(self, href,tab_open_retries):
        """
        Opens a URL in a new browser tab and returns the new window handle.

        It works by recording the set of window handles before opening the new
        tab, and then finding the handle that was added.

        Args:
            href (str): The URL to open.
            tab_open_retries (int): The number of times to check for a new handle.

        Returns:
            The window handle (string) of the newly opened tab.
        """
        before_handles = set(self.driver.window_handles)
        # Open new tab with specified href - this opens a new tab in most browsers
        self.driver.execute_script("window.open(arguments[0], '_blank');", href)

        # Wait for the new handle to appear
        new_handle = None
        for _ in range(tab_open_retries):
            after_handles = set(self.driver.window_handles)
            diff = after_handles - before_handles
            if diff:
                new_handle = diff.pop()
                break
            time.sleep(0.5 + random.random() * 0.5)  # jittered wait
        if not new_handle:
            raise RuntimeError(f"New tab did not appear for href={href}")
        return new_handle

    def get_post_title_data(self, href_string, timeout=5):
        """
        Executes a JavaScript snippet to extract post title, timestamp, and author data.

        The JavaScript code searches for a specific DOM structure that typically
        contains the post's header information. It looks for the innermost `div`
        that contains both a link (`<a>`) to the author's profile and a `<time>` element.

        Args:
            href_string (str): The profile slug (e.g., `"/ladbible/"`) used to
                               identify the correct author link.

        Returns:
            A dictionary containing the extracted data, or None if not found.
        """
        random_delay(0.4, 2.3)  # small wait to ensure content is fully loaded
        href_string_js = json.dumps(href_string)  # safely quote special characters
        
        js_code = f"""
        function getPostTitleData(variableA) {{
            const divs = Array.from(document.querySelectorAll('div'));
            let innermostDiv = null;

            for (const div of divs) {{
                const aEl = div.querySelector(`a[href="${{variableA}}"]`);
                const timeEl = div.querySelector('time');

                if (aEl && timeEl) {{
                    const childDivs = div.querySelectorAll('div');
                    let hasNestedBoth = false;

                    for (const child of childDivs) {{
                        if (child.querySelector(`a[href="${{variableA}}"]`) && child.querySelector('time')) {{
                            hasNestedBoth = true;
                            break;
                        }}
                    }}

                    if (!hasNestedBoth) {{
                        innermostDiv = div;
                    }}
                }}
            }}

            if (!innermostDiv) return null;

            const aEl = innermostDiv.querySelector(`a[href="${{variableA}}"]`);
            const timeEl = innermostDiv.querySelector('time');

            const data = {{
                topDivClass: innermostDiv.className,
                aHref: aEl ? aEl.getAttribute('href') : null,
                aSrc: aEl ? aEl.getAttribute('src') : null,
                timeDatetime: timeEl ? timeEl.getAttribute('datetime') : null,
                siblingTexts: []
            }};

            const parent = innermostDiv.parentElement;
            if (parent) {{
                const siblings = Array.from(parent.children).filter(el => el !== innermostDiv);
                data.siblingTexts = siblings
                    .map(sib => sib.textContent.trim())
                    .filter(t => t.length > 0);
            }}

            return data;
        }}

        return getPostTitleData({href_string_js});
        """

        logger.info(f"Executing JS - {js_code} to get post title data for href: {href_string}")
        return self.driver.execute_script(js_code)

    def on_posts_batch_ready(self, local_jsonl_path: str) -> None:
        gcs_uri = self.uploader.upload_and_enqueue(
            local_path=local_jsonl_path,
            kind="post",
        )

    def on_comments_batch_ready(self, local_jsonl_path: str) -> None:
        gcs_uri = self.uploader.upload_and_enqueue(
            local_path=local_jsonl_path,
            kind="comment",
        )

    def _extract_comments_from_captured_requests(self, driver, config, batch_scrolls: int = 6):
        """
        Incrementally expands comment threads and fetches post data after each batch.

        This method repeatedly invokes `click_all_reply_buttons_gently` in small batches
        until no more reply buttons are found. After each batch, it refreshes the post data.

        Args:
            driver: The Selenium WebDriver instance.
            config: The application's configuration object.
            batch_scrolls: Number of scroll loops to perform per batch before refreshing data.
        """
        container_info = find_comment_container(driver)
        container = container_info.get("selector") if container_info else None
        self.reply_expander = ReplyExpander.with_container(driver, container, max_clicks=5)
        total_clicked = 0
        MAX_CLICKS_ALLOWED = 10
        total_clicked_texts = []
        all_logs = []
        batch_index = 0
        rate_limit_detected = 0
        is_commentdata_saved = False
        # Initial extraction from embed script
        # this call doesnt get recorded into perf logs, as these first few comments are embedded in the HTML.
        initial_comments_data = extract_script_embedded_comments(self.driver)
        logger.info(f"Initial embedded comments extraction returned {len(initial_comments_data.get('flattened_data', []))} items.")
        is_saved = self.config.main.registry.save_parsed_results(initial_comments_data, config.data.post_entity_path)
        if is_saved:
            is_commentdata_saved = True
        # self.config.main.registry.get_posts_data(self.config, self.config.data.post_page_data_key, data_type="post")

        while True:
            batch_index += 1
            logger.debug(f"Starting batch {batch_index}: performing {batch_scrolls} scroll loops.")

            # --- RATE LIMIT HANDLING ---
            if self.rate_limit_detected:
                # Check if cooldown has expired
                if time.time() >= self.rate_limit_reset_time:
                    self.rate_limit_detected = 0
                    self.rate_limit_reset_time = None
                    self._save_rate_limit_state()
                    logger.info("Rate limit cooldown expired — resuming normal reply expansion.")
                else:
                    remaining = int(self.rate_limit_reset_time - time.time())
                    logger.info(f"Rate limit active — performing only_scroll for next {remaining}s.")
                    _ = self.reply_expander.only_scroll(container, scroll_steps=30)
                    # time.sleep(random.uniform(1.0, 2.0))
                    break
                
            result = self.reply_expander.expand_replies()
            clicked_count = result.get("clickedCount", 0)
            clicked_texts = result.get("clickedTexts", [])
            logs = result.get("logs", [])

            if clicked_count <= 2:
                if self._handle_comment_load_error(driver, container):
                    # --- EXPONENTIAL COOLDOWN LOGIC ---
                    self.rate_limit_attempts += 1
                    base_min, base_max = 240, 360  # base range = 4–6 minutes
                    multiplier = min(2 ** (self.rate_limit_attempts - 1), 16)  # cap at 8x growth
                    cooldown_seconds = random.uniform(base_min, base_max) * multiplier
                    # ----------------------------------

                    self.rate_limit_detected = True
                    self.rate_limit_reset_time = time.time() + cooldown_seconds
                    self._save_rate_limit_state()
                    logger.warning(
                        f"Rate limit triggered (attempt #{self.rate_limit_attempts}). "
                        f"Cooldown for {cooldown_seconds/60:.1f} minutes "
                        f"(multiplier={multiplier}x)."
                    )
                    continue  # skip to next loop iteration after retry delay
                # Exit condition: no more new reply buttons to click
                logger.info("No reply buttons clicked in this batch.")
                break

            total_clicked += clicked_count
            total_clicked_texts.extend(clicked_texts)
            all_logs.extend(logs)

            if total_clicked >= MAX_CLICKS_ALLOWED:
                logger.info(f"Reached max clicks allowed ({MAX_CLICKS_ALLOWED}). Stopping further expansion." 
                f"Final clicked count: {total_clicked}")
                break
            
            logger.info(
                f"Batch {batch_index} complete — clicked {clicked_count} reply buttons "
                f"(total so far: {total_clicked})."
                f"some clicked texts: {clicked_texts[:3]}..."
            )

            # Refresh post data after every batch
            try:
                logger.debug("Refreshing post data from captured network requests...")
                is_saved = self.config.main.registry.get_posts_data(
                    self.config, self.config.data.post_page_data_key, data_type="post"
                )
                if is_saved:
                    is_commentdata_saved = True
            except Exception as e:
                logger.warning(f"Failed to refresh post data: {e}")

            # Small pause between batches for realism and stability
            time.sleep(random.uniform(1.5, 3.0))

        is_saved = self.config.main.registry.get_posts_data(self.config, self.config.data.post_page_data_key, data_type="post")
        if is_saved or is_commentdata_saved:
            self.on_comments_batch_ready(self.config.data.post_entity_path)

    def _handle_comment_load_error_bk(self, driver, container):
        try:
            error_header = container.find_elements(By.XPATH, ".//h2[contains(text(),\"Comments can't be loaded\")]")
            error_message = container.find_elements(By.XPATH, ".//span[contains(text(), 'Please try again later')]")
            if error_header or error_message:
                logger.warning("Detected 'Comments can't be loaded right now' message. Pausing and retrying...")
                time.sleep(random.uniform(4.5, 8.0))
                driver.refresh()  # optional, if the comment DOM becomes unstable
                return True
            return False
        except Exception as e:
            logger.debug(f"Error while checking for comment load failure: {e}")
            return False

    def _handle_comment_load_error(self, driver, container):
        """
        Detects Instagram's 'Comments can't be loaded' type errors.

        Works whether 'container' is a CSS selector string or a WebElement.
        Uses CSS selectors only (no XPath). Case-insensitive text detection.
        """
        try:
            # Resolve container: if a string selector, find it first
            if isinstance(container, str):
                try:
                    container_el = driver.find_element(By.CSS_SELECTOR, container)
                except Exception:
                    logger.debug(f"Comment container not found for selector: {container}")
                    return False
            else:
                container_el = container

            # Find all headers and spans inside the comment container
            h2_elements = container_el.find_elements(By.CSS_SELECTOR, "h2")
            span_elements = container_el.find_elements(By.CSS_SELECTOR, "span")

            # Collect and normalize text (strip + lower)
            texts = [el.text.strip().lower() for el in h2_elements + span_elements if el.text.strip()]
            combined_text = " ".join(texts)

            # Known Instagram comment load error phrases
            error_signals = [
                "comments can't be loaded right now",
                "please try again later",
                "couldn't load comments",
                "couldn't load comments",
                "error loading comments"
            ]

            if any(sig in combined_text for sig in error_signals):
                logger.warning("Detected 'Comments can't be loaded' message. Pausing and retrying...")
                time.sleep(random.uniform(4.5, 8.0))
                driver.refresh()
                return True

            return False

        except Exception as e:
            logger.debug(f"Error while checking for comment load failure: {e}")
            return False


    def _load_rate_limit_state(self):
        """Load cooldown state from disk, if it exists."""
        if not os.path.exists(self._state_file):
            logger.debug("No previous rate limit state file found.")
            return

        try:
            with open(self._state_file, "r") as f:
                data = json.load(f)
            self.rate_limit_detected = data.get("rate_limit_detected", False)
            self.rate_limit_reset_time = data.get("rate_limit_reset_time")
            self.rate_limit_attempts = data.get("rate_limit_attempts", 0)

            if self.rate_limit_reset_time and time.time() >= self.rate_limit_reset_time:
                # cooldown expired — reset
                self.rate_limit_detected = False
                self.rate_limit_reset_time = None
                self.rate_limit_attempts = 0
                self._save_rate_limit_state()
                logger.info("Loaded expired rate limit state — reset to defaults.")
            else:
                logger.info("Loaded persisted rate limit state from disk.")

        except Exception as e:
            logger.warning(f"Failed to load rate limit state: {e}")

    def _save_rate_limit_state(self):
        """Persist cooldown state to disk."""
        try:
            with open(self._state_file, "w") as f:
                json.dump({
                    "rate_limit_detected": self.rate_limit_detected,
                    "rate_limit_reset_time": self.rate_limit_reset_time,
                    "rate_limit_attempts": self.rate_limit_attempts
                }, f, indent=2)
            logger.debug("Saved rate limit state to disk.")
        except Exception as e:
            logger.warning(f"Failed to save rate limit state: {e}")
