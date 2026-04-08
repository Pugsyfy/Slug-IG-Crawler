from datetime import datetime, timezone
import os
from pathlib import Path
from re import I
import sys
import threading
import time
import json
import pickle
import random
import traceback
from typing import Iterator, Dict, List, Any, Optional
from urllib.parse import urlparse

from pathlib import Path
from datetime import datetime, timezone
from io import BytesIO
from PIL import Image

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
from igscraper.paths import get_cached_browser_binaries
from igscraper.utils import (
    HumanScroller,
    click_all_reply_buttons_gently,
    extract_instagram_shortcode,
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
    update_post_entity_path,
    write_and_run_curl_script,
    get_shortcode_web_info,
    list_logged_urls,
    get_first_link_href_base,
    classify_mp4_files,
    unmute_if_muted
)
from igscraper.utils.video_finalizer import (
    generate_video_from_screenshots,
    upload_video_to_gcs,
    cleanup_local_files,
    generate_video_name,
)
from igscraper.services.full_media_download_script import write_and_run_full_download_script
from igscraper.services.enqueue_client import PostgresConfig, FileEnqueuer
from igscraper.services.upload_enqueue import GcsUploadConfig, UploadAndEnqueue

import pdb
import re
import subprocess


logger = get_logger(__name__)

# Default local (macOS) paths when env and optional config omit binaries.
_DEFAULT_LOCAL_CHROME_BIN = (
    "/Users/shang/my_work/ig_profile_scraper/"
    "chrome-mac-arm64/"
    "Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
)
_DEFAULT_LOCAL_CHROMEDRIVER_BIN = "/opt/homebrew/bin/chromedriver"
# Dockerfile ENV defaults when use_docker=true and CHROME_* env not set.
_DOCKER_CHROME_BIN = "/opt/chrome-linux64/chrome"
_DOCKER_CHROMEDRIVER_BIN = "/opt/chromedriver-linux64/chromedriver"


# ⚠️ Suspicious navigation: chrome://new-tab-page/ patch it too
def assert_chrome_versions_match(chrome_bin: str, chromedriver_bin: str):
    def major_version(cmd):
        out = subprocess.check_output([cmd, "--version"], text=True)
        m = re.search(r"(\d+)\.", out)
        if not m:
            raise RuntimeError(f"Cannot parse version from: {out}")
        return m.group(1), out.strip()

    chrome_major, chrome_full = major_version(chrome_bin)
    driver_major, driver_full = major_version(chromedriver_bin)

    if chrome_major != driver_major:
        raise RuntimeError(
            "Chrome / ChromeDriver version mismatch:\n"
            f"  Chrome:       {chrome_full}\n"
            f"  ChromeDriver: {driver_full}"
        )

    logger.info(
        f"Chrome versions OK: {chrome_full} | {driver_full}"
    )


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
        self.screenshot_stop_event = threading.Event()
        self.profile_page = None
        self.reply_expander = None
        self.rate_limit_detected = False
        self.rate_limit_reset_time = 0
        self.rate_limit_attempts = 0 
        self.global_seen_comment_ids: set[str] = set()
        self.scroller = None
        # thor_worker_id will be set by Pipeline after initialization
        self.thor_worker_id: str | None = None
        pg_cfg = PostgresConfig.from_env()
        logger.debug(f"Postgres config: {pg_cfg}")
        enqueuer = FileEnqueuer(pg_cfg)
        # thor_worker_id will be set by Pipeline after initialization
        # We'll set it on enqueuer when thor_worker_id is available
        self._enqueuer = enqueuer
        gcs_cfg = GcsUploadConfig(bucket_name=self.config.main.gcs_bucket_name)
        self.uploader = UploadAndEnqueue(
            gcs_cfg,
            enqueuer,
            push_to_gcs=self.config.main.push_to_gcs,
        )
        self._state_file = "rate_limit_state.json"  # persistent file
        self._load_rate_limit_state()
        self.COMMENT_MODEL_KEYS = {
    "xdt_api__v1__media__media_id__comments__connection",
    # "xdt_api__v1__media__media_id__comments__parent_comment_id__child_comments__connection",
}

        self.COMMENT_ID_KEY_RE = re.compile(
            r"(comment).*?(?:\$\$pk|\$\$id|_pk|_id|\.pk|\.id)$",
            re.IGNORECASE,
        )

    def _resolve_browser_binaries(self) -> tuple[str, str]:
        """
        Chrome + ChromeDriver paths. CHROME_BIN and CHROMEDRIVER_BIN always win when set.

        If unset: Docker uses image paths; local uses optional main.chrome_binary_path /
        main.chromedriver_binary_path then built-in macOS defaults.
        """
        m = self.config.main

        def _strip_or_none(val: Optional[str]) -> Optional[str]:
            if val is None:
                return None
            t = val.strip()
            return t or None

        chrome = os.environ.get("CHROME_BIN")
        driver = os.environ.get("CHROMEDRIVER_BIN")

        if self.config.main.use_docker:
            chrome = chrome or _DOCKER_CHROME_BIN
            driver = driver or _DOCKER_CHROMEDRIVER_BIN
        else:
            chrome = chrome or _strip_or_none(getattr(m, "chrome_binary_path", None))
            driver = driver or _strip_or_none(getattr(m, "chromedriver_binary_path", None))
            if not chrome or not driver:
                c_cached, d_cached = get_cached_browser_binaries()
                if not chrome and c_cached:
                    chrome = str(c_cached)
                if not driver and d_cached:
                    driver = str(d_cached)
            chrome = chrome or _DEFAULT_LOCAL_CHROME_BIN
            driver = driver or _DEFAULT_LOCAL_CHROMEDRIVER_BIN

        logger.info(
            "Browser binaries (CHROME_BIN/CHROMEDRIVER_BIN override when set): "
            f"chrome={chrome!r}, chromedriver={driver!r}"
        )
        return chrome, driver

    # def startOg(self):
    #     """
    #     Starts the Selenium WebDriver, configures it for stealth, and logs in.

    #     - Sets up Chrome options to evade bot detection.
    #     - Initializes the Chrome driver using webdriver-manager.
    #     - Patches the driver to monitor for suspicious navigation.
    #     - Logs in using cookies specified in the configuration.
    #     - Initializes the ProfilePage object for page interactions.
    #     """
    #     options = Options()
    #     caps = options.to_capabilities()
    #     # Only keep network events
    #     perf_log_prefs = {
    #         "enableNetwork": True
    #     }
    #     options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    #     options.set_capability("goog:perfLoggingPrefs", perf_log_prefs)
    #     # caps = DesiredCapabilities.CHROME.copy()
    #     # caps['goog:loggingPrefs'] = {'performance': 'ALL'}
    #     # caps["goog:perfLoggingPrefs"] = perf_log_prefs

    #     # --- Anti-detection settings from test_sel.py ---
    #     options.add_argument("--disable-blink-features=AutomationControlled")
    #     # options.add_argument("--auto-open-devtools-for-tabs") # testing for dev UI tools
    #     options.add_experimental_option("excludeSwitches", ["enable-automation"])
    #     options.add_experimental_option('useAutomationExtension', False)
    #     options.add_argument("--autoplay-policy=no-user-gesture-required")
    #     options.add_argument("--disable-background-timer-throttling")
    #     options.add_argument("--disable-renderer-backgrounding")
    #     options.add_argument("--disable-backgrounding-occluded-windows")
    #     # Human-like settings
    #     options.add_argument("--window-size=1920,1080")
    #     options.add_argument("--start-maximized")

    #     # Use user_agent from config or a default one
    #     user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36"
    #     options.add_argument(f'user-agent={user_agent}')

    #     if self.config.main.headless:
    #         options.add_argument("--headless=new")

    #     # Use WebDriver Manager for automatic driver management
    #     try:
    #         service = Service(ChromeDriverManager().install())
    #         self.driver = webdriver.Chrome(service=service, options=options)
    #         self.driver = patch_driver(self.driver)
    #     except Exception as e:
    #         logger.error(f"Failed to initialize Chrome driver with webdriver-manager: {e}")
    #         logger.info("Falling back to default webdriver initialization.")
    #         self.driver = webdriver.Chrome(options=options)
    #         ## Patch driver to stop the script if detection happens and we are rerouted to a captcha page
    #         self.driver = patch_driver(self.driver)

    #     self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    #     self.setup_network()
    #     self._login_with_cookies()
    #     self.profile_page = ProfilePage(self.driver, self.config)
    #     # ---- start periodic screenshots ----
    #     # if self.config.main.enable_screenshots:
    #     #     self.screenshot_thread = threading.Thread(
    #     #         target=self._screenshot_worker,
    #     #         kwargs={"interval_sec": 7},
    #     #         daemon=True
    #     #     )
    #     #     self.screenshot_thread.start()
    #     #     logger.info("Screenshot worker started (7s interval)")


    def start(self):
        """
        Starts the Selenium WebDriver, configures it for stealth,
        enables network tracking, and logs in using cookies.
        """

        options = Options()

        # ------------------------------------------------------------------
        # Performance / Network logging (CDP)
        # ------------------------------------------------------------------
        perf_log_prefs = {"enableNetwork": True}
        options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
        # options.set_capability("goog:perfLoggingPrefs", perf_log_prefs)

        # ------------------------------------------------------------------
        # Anti-detection / stealth flags
        # ------------------------------------------------------------------
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        options.add_argument("--autoplay-policy=no-user-gesture-required")
        options.add_argument("--disable-background-timer-throttling")
        options.add_argument("--disable-renderer-backgrounding")
        options.add_argument("--disable-backgrounding-occluded-windows")

        # ------------------------------------------------------------------
        # Viewport (mandatory for screenshots)
        # ------------------------------------------------------------------
        options.add_argument("--window-size=1920,1080")

        # ------------------------------------------------------------------
        # Headless
        # ------------------------------------------------------------------
        if self.config.main.headless:
            options.add_argument("--headless=new")


        # --------------------------------------------------
        # Environment-specific paths (CHROME_BIN / CHROMEDRIVER_BIN respected in all modes)
        # --------------------------------------------------
        if self.config.main.use_docker:
            profile_dir = os.getenv("IGSCRAPER_CHROME_PROFILE","/tmp/chrome-profile")
            platform = "Linux x86_64"

            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")

        else:
            profile_dir = os.getenv("IGSCRAPER_CHROME_PROFILE", "/tmp/chrome-profile")
            platform = "Linux x86_64"  # intentionally Linux-like

            options.add_argument("--remote-debugging-pipe")

        chrome_bin, chromedriver_bin = self._resolve_browser_binaries()

        # --------------------------------------------------
        # Append worker_id and random suffix to profile path
        # --------------------------------------------------
        if profile_dir:
            # Generate random 3-character alphanumeric string
            random_suffix = ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=3))
            
            # Append worker_id and random suffix if thor_worker_id is available
            if self.thor_worker_id:
                profile_dir = f"{profile_dir}-{self.thor_worker_id}-{random_suffix}"
            else:
                # Fallback: just append random suffix if worker_id not available
                profile_dir = f"{profile_dir}-{random_suffix}"
                logger.warning("thor_worker_id not set, using profile path without worker_id suffix")

        # --------------------------------------------------
        # Ensure profile directory exists (Chrome requires it)
        # --------------------------------------------------
        if profile_dir:
            os.makedirs(profile_dir, exist_ok=True)

        # --------------------------------------------------
        # Assert version lock
        # --------------------------------------------------
        assert_chrome_versions_match(chrome_bin, chromedriver_bin)

        # --------------------------------------------------
        # Browser identity (must never drift)
        # --------------------------------------------------
        user_agent = (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/143.0.0.0 Safari/537.36"
        )

        options.binary_location = chrome_bin
        options.add_argument(f"--user-agent={user_agent}")
        options.add_argument(f"--user-data-dir={profile_dir}")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-blink-features=AutomationControlled")

        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)


        # --------------------------------------------------
        # Start WebDriver
        # --------------------------------------------------
        service = Service(chromedriver_bin)

        self.driver = webdriver.Chrome(
            service=service,
            options=options
        )

        # options.add_argument(f"--user-agent={user_agent}")
        # options.add_argument("--user-data-dir=/tmp/ig_profile")

        # Apply custom driver patching (captcha / redirect detection, etc.)
        self.driver = patch_driver(self.driver)

        # --------------------------------------------------
        # Deterministic platform override
        # --------------------------------------------------
        self.driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": f"""
                    Object.defineProperty(navigator, 'platform', {{
                        get: () => '{platform}'
                    }});
                """
            }
        )
        # ------------------------------------------------------------------
        # JS-level stealth patches
        # ------------------------------------------------------------------
        # self.driver.execute_script(
        #     "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        # )

        # self.driver.execute_cdp_cmd(
        #     "Page.addScriptToEvaluateOnNewDocument",
        #     {
        #         "source": """
        #         Object.defineProperty(navigator, 'platform', {
        #             get: () => arguments[0]
        #         });
        #         """,
        #         "args": [
        #             "Linux x86_64" if self.config.main.use_docker else "MacIntel"
        #         ]
        #     }
        # )

        # ------------------------------------------------------------------
        # Stabilize CDP before enabling Network
        # ------------------------------------------------------------------
        self.driver.get("about:blank")

        self.setup_network()

        # ------------------------------------------------------------------
        # Login + page bootstrap
        # ------------------------------------------------------------------
        self._login_with_cookies()
        self.profile_page = ProfilePage(self.driver, self.config)
        self.scroller = HumanScroller(self.driver)



    # def start(self):
    #     """
    #     Stable Selenium startup:
    #     - Same Chrome
    #     - Same profile
    #     - Same UA
    #     - Same platform
    #     - Works on macOS + Docker
    #     """

    #     options = Options()

    #     options.set_capability(
    #         "goog:loggingPrefs",
    #         {"performance": "ALL"}
    #     )

    #     # --------------------------------------------------
    #     # Version-locked browser identity
    #     # --------------------------------------------------
    #     if self.config.main.use_docker:
    #         options.binary_location = os.environ["CHROME_BIN"]
    #         chromedriver_path = os.environ["CHROMEDRIVER_BIN"]
    #         platform = "Linux x86_64"
    #         profile_dir = "/data/chrome-profile"

    #         options.add_argument("--no-sandbox")
    #         options.add_argument("--disable-dev-shm-usage")
    #         options.add_argument("--disable-gpu"

    #     else:
    #         options.binary_location = (
    #             "/Users/shang/my_work/ig_profile_scraper/"
    #             "chrome-mac-arm64/"
    #             "Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
    #         )
    #         chromedriver_path = "/opt/homebrew/bin/chromedriver"
    #         platform = "Linux x86_64"  # intentionally Linux-like
    #         profile_dir = "/Users/shang/.ig_chrome_profile"

    #         options.add_argument("--remote-debugging-pipe")

    #     # --------------------------------------------------
    #     # SAME USER AGENT EVERYWHERE
    #     # --------------------------------------------------
    #     user_agent = (
    #         "Mozilla/5.0 (X11; Linux x86_64) "
    #         "AppleWebKit/537.36 (KHTML, like Gecko) "
    #         "Chrome/143.0.0.0 Safari/537.36"
    #     )

    #     # --------------------------------------------------
    #     # REQUIRED FLAGS
    #     # --------------------------------------------------
    #     options.add_argument(f"--user-agent={user_agent}")
    #     options.add_argument(f"--user-data-dir={profile_dir}")
    #     options.add_argument("--window-size=1920,1080")
    #     options.add_argument("--disable-blink-features=AutomationControlled")

    #     options.add_experimental_option("excludeSwitches", ["enable-automation"])
    #     options.add_experimental_option("useAutomationExtension", False)

    #     if self.config.main.headless:
    #         options.add_argument("--headless=new")

    #     # --------------------------------------------------
    #     # Start driver
    #     # --------------------------------------------------
    #     service = Service(chromedriver_path)

    #     self.driver = webdriver.Chrome(
    #         service=service,
    #         options=options
    #     )

    #     # --------------------------------------------------
    #     # Platform override (early, deterministic)
    #     # --------------------------------------------------
    #     self.driver.execute_cdp_cmd(
    #         "Page.addScriptToEvaluateOnNewDocument",
    #         {
    #             "source": f"""
    #                 Object.defineProperty(navigator, 'platform', {{
    #                     get: () => '{platform}'
    #                 }});
    #             """
    #         }
    #     )

    #     # --------------------------------------------------
    #     # Bootstrap
    #     # --------------------------------------------------
    #     self.driver.get("about:blank")
    #     self.setup_network()

    #     # ⚠️ DO NOT inject cookies if profile exists
    #     # if not os.path.exists(os.path.join(profile_dir, "Default")):
    #     self._login_with_cookies()

    #     self.profile_page = ProfilePage(self.driver, self.config)


    def setup_network(self):
        # Enable network tracking
        self.driver.execute_cdp_cmd("Network.enable", {})
        self.driver.execute_cdp_cmd("Network.clearBrowserCache", {})
        self.driver.execute_cdp_cmd("Network.clearBrowserCookies", {})
        self.driver.set_script_timeout(180)
        self.driver.command_executor.set_timeout(300) 

    # def _login_with_cookies(self):
    #     """
    #     Loads cookies from a file to authenticate the browser session.

    #     The browser must first navigate to the domain ('instagram.com') before
    #     cookies can be added. The path to the cookie file is read from the
    #     configuration. If the file doesn't exist, the program will exit.
    #     """
    #     if not self.config.data.cookie_file or not os.path.exists(self.config.data.cookie_file):
    #         logger.info("No cookie file specified in config or cookie file does not exist. Exiting early.")
    #         sys.exit(1)

    #     logger.info(f"Attempting to log in using cookies from {self.config.data.cookie_file}")
    #     self.driver.get("https://www.instagram.com/")  # Must visit domain first

    #     try:
    #         with open(self.config.data.cookie_file, "rb") as f:
    #             cookies = pickle.load(f)
    #     except (pickle.UnpicklingError, EOFError) as e:
    #         logger.error(f"Could not load cookies from {self.config.data.cookie_file}. Error: {e}")
    #         return

    #     for cookie in cookies:
    #         # Selenium expects 'expiry' to be int if present
    #         if 'expiry' in cookie and isinstance(cookie['expiry'], float):
    #             cookie['expiry'] = int(cookie['expiry'])
    #         self.driver.add_cookie(cookie)

    #     self.driver.refresh()  # Apply cookies
    #     logger.info("✅ Successfully logged in using cookies.")
    #     time.sleep(3) # Wait a bit for page to settle


    def _login_with_cookies(self):
        """
        Ensure Instagram is logged in.
        Uses cookies only if not already authenticated.
        """

        # --------------------------------------------------
        # 1. Check if already logged in
        # --------------------------------------------------
        self.driver.get("https://www.instagram.com/")
        time.sleep(3)

        current_url = self.driver.current_url

        # --------------------------------------------------
        # Detect login UI (reliable)
        # --------------------------------------------------
        login_elements = self.driver.find_elements(
            By.XPATH,
            "//input[@name='username'] | //input[@name='password']"
        )

        body_text = self.driver.find_element(By.TAG_NAME, "body").text.lower()

        if not login_elements and not any(word in body_text for word in ["forgot", "forgotten"]):
            logger.info("Already logged in — skipping cookie injection")
            return

        # --------------------------------------------------
        # 2. Not logged in → try cookies
        # --------------------------------------------------
        cookie_path = self.config.data.cookie_file

        if not cookie_path or not os.path.exists(cookie_path):
            raise RuntimeError("Not logged in and no cookie file available")

        logger.info(f"Attempting cookie login using {cookie_path}")

        try:
            with open(cookie_path, "r") as f:
                cookies = json.load(f)
        except Exception as e:
            raise RuntimeError(f"Failed to load cookie file: {e}")

        for cookie in cookies:
            cookie.pop("sameSite", None)
            if "expiry" in cookie:
                cookie["expiry"] = int(cookie["expiry"])

            try:
                self.driver.add_cookie(cookie)
            except Exception as e:
                logger.debug(f"Skipping cookie {cookie.get('name')}: {e}")

        # --------------------------------------------------
        # 3. Reload and validate
        # --------------------------------------------------
        self.driver.get("https://www.instagram.com/")
        time.sleep(4)

        if "login" in self.driver.current_url:
            raise RuntimeError("Cookie login failed — still on login page")

        body = self.driver.find_element(By.TAG_NAME, "body").text.lower()
        if "something went wrong" in body:
            raise RuntimeError("Cookie login failed — Instagram error page")

        logger.info("✅ Logged in successfully (cookie bootstrap)")



    def stop(self):
        """
        Quits the WebDriver and closes all associated browser windows.
        
        Also finalizes screenshots by generating a video, uploading to GCS, and cleaning up local files.
        This hook is called during scraper shutdown, after scraping completes and before process exit.
        """
        # Stop screenshot worker first
        self.screenshot_stop_event.set()
        if hasattr(self, "screenshot_thread"):
            self.screenshot_thread.join(timeout=2)
        
        # Close browser first (after scraping completes)
        if self.driver:
            self.driver.quit()
        
        # Finalize screenshots (generate video, upload, cleanup)
        # This runs after browser shutdown but before process exit
        # Errors are logged but don't block shutdown
        if self.config.main.enable_screenshots:
            self._finalize_screenshots()

    def _finalize_screenshots(self):
        """
        Shutdown-time artifact finalization: generate video from screenshots, upload to GCS, cleanup local files.
        
        This method:
        1. Generates an MP4 video from all .webp screenshots in shot_dir
        2. Uploads the video to the configured GCS bucket
        3. Deletes all local screenshots and the video file
        
        Works for both PROFILE (mode 1) and POST (mode 2) jobs.
        Failures are logged but don't block shutdown.
        """
        try:
            # Resolve screenshot directory
            shot_dir = Path(self.config.data.shot_dir).expanduser().resolve()
            
            if not shot_dir.exists():
                logger.info(f"[finalize_screenshots] Screenshot directory does not exist: {shot_dir}. Nothing to finalize.")
                return

            # Count screenshots
            webp_files = list(shot_dir.glob("*.webp"))
            screenshot_count = len(webp_files)
            logger.info(f"[finalize_screenshots] Found {screenshot_count} screenshots in {shot_dir}")

            if screenshot_count < 2:
                logger.warning(
                    f"[finalize_screenshots] Only {screenshot_count} screenshot(s) found, need at least 2. "
                    "Skipping video generation and cleanup."
                )
                return

            # Generate video filename
            video_name = generate_video_name(
                mode=self.config.main.mode,
                consumer_id=self.config.main.consumer_id,
                profile_name=self.config.main.target_profile if self.config.main.mode == 1 else None,
                run_name=self.config.main.run_name_for_url_file if self.config.main.mode == 2 else None,
                worker_id=self.thor_worker_id,
            )

            if not video_name:
                logger.error("[finalize_screenshots] Failed to generate video name. Skipping video generation.")
                return

            # Generate video in the screenshot directory (in-place)
            video_path = shot_dir / video_name
            logger.info(f"[finalize_screenshots] Generating video: {video_path}")

            success = generate_video_from_screenshots(
                screenshot_dir=shot_dir,
                output_path=video_path,
                fps=2.5,
                target_height=640,
            )

            if not success:
                logger.error("[finalize_screenshots] Video generation failed. Skipping upload and cleanup.")
                return

            logger.info(f"[finalize_screenshots] Video created successfully: {video_path}")

            bucket_name = self.config.main.gcs_bucket_name
            gcs_uri = None
            push_gcs = self.config.main.push_to_gcs

            if push_gcs == 0:
                logger.info(
                    "[finalize_screenshots] push_to_gcs=0: keeping video local (no GCS upload): %s",
                    video_path.resolve(),
                )
            else:
                # Upload to GCS
                if not bucket_name:
                    logger.error("[finalize_screenshots] gcs_bucket_name is not configured. Skipping upload.")
                else:
                    logger.info(f"[finalize_screenshots] Uploading to GCS bucket: {bucket_name!r}")
                    gcs_object_name = f"vid_log/{video_name}"
                    gcs_uri = upload_video_to_gcs(
                        local_video_path=video_path,
                        bucket_name=bucket_name,
                        gcs_object_name=gcs_object_name,
                    )

                if gcs_uri:
                    logger.info(f"[finalize_screenshots] Video uploaded to GCS: {gcs_uri}")
                else:
                    logger.error("[finalize_screenshots] GCS upload failed, but continuing with cleanup")

            if push_gcs == 0:
                logger.info("[finalize_screenshots] push_to_gcs=0: skipping local cleanup (screenshots + video kept).")
            else:
                # Cleanup: delete all screenshots and video file
                # This runs even if upload failed (best-effort cleanup)
                cleanup_local_files(
                    screenshot_dir=shot_dir,
                    video_path=video_path,
                )

            logger.info("[finalize_screenshots] Screenshot finalization completed")

        except Exception as e:
            # Fail-safe: log error but don't block shutdown
            logger.error(f"[finalize_screenshots] Unexpected error during finalization: {e}", exc_info=True)

    def start_screenshot_worker(self):
        if not self.config.main.enable_screenshots:
            return

        # prevent double start
        if getattr(self, "screenshot_thread", None) and self.screenshot_thread.is_alive():
            logger.debug("Screenshot worker already running")
            return

        self.screenshot_stop_event.clear()

        self.screenshot_thread = threading.Thread(
            target=self._screenshot_worker,
            kwargs={"interval_sec": 7},
            daemon=True
        )
        self.screenshot_thread.start()

        logger.debug("Screenshot worker started (7s interval)")


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
            logger.debug(f"Loaded {len(urls)} post URLs from {file_path}.")
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
        logger.debug(f"Saved {len(urls)} post URLs to {file_path}.")

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
            logger.debug(f"Loaded {len(processed)} processed post URLs from {file_path}.")
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
                logger.debug("Posts data was saved during collection. Trying to push to gs bucket")
                self.on_posts_batch_ready(self.config.data.profile_path)
        else:
            urls = cached

        # Filter out already processed urls
        processed_data_path = self.config.data.metadata_path
        processed = self._load_processed_urls(processed_data_path)
        urls = [u for u in urls if u not in processed]

        logger.debug(f"Returning {len(urls)} post URLs after filtering out {len(processed)} processed ones.")
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
        # Timing: Start total time (just before opening the post tab)
        total_time_start = time.perf_counter()
        active_time_start = time.perf_counter()
        active_time_accumulated = 0.0
        error_type = None
        status = "success"
        
        # Extract content_id and creator_handle
        post_shortcode = extract_instagram_shortcode(post_url)
        content_id = post_shortcode if post_shortcode else post_url
        
        # Get creator_handle: prefer target_profile, fallback to extracting from URL
        creator_handle = getattr(self.config.main, 'target_profile', None)
        if not creator_handle:
            # Try to extract from URL (format: /username/p/... or /username/reel/...)
            try:
                parsed = urlparse(post_url)
                parts = [p for p in parsed.path.strip("/").split("/") if p]
                if len(parts) > 0 and parts[0] not in ["p", "reel"]:
                    creator_handle = parts[0]
                else:
                    creator_handle = getattr(self.config.main, 'run_name_for_url_file', 'unknown')
            except Exception:
                creator_handle = getattr(self.config.main, 'run_name_for_url_file', 'unknown')
        
        try:
            # switch to the new tab
            self.driver.switch_to.window(tab_handle)
            # unmute_if_muted(self.driver, 0.2)

            # del self.driver.requests  # Clear any previous requests to avoid memory bloat
            logger.debug(f"Switched to tab {tab_handle} for post {post_index} ({post_url}). Refreshing page.")
            # self.driver.refresh()
            
            # Active time: tab switch
            active_time_end = time.perf_counter()
            active_time_accumulated += (active_time_end - active_time_start)
            
            # Sleep (excluded from active time)
            random_delay(2.4, 4.0)  # Wait for at least 3 seconds for the page to load after refresh.
            active_time_start = time.perf_counter()
            # Anti Bot measure
            if random.choice([0,0,1,1,1,1,1]) == 0:
                human_mouse_move(self.driver,duration=self.config.main.human_mouse_move_duration)
                # Active time: human_mouse_move
                active_time_end = time.perf_counter()
                active_time_accumulated += (active_time_end - active_time_start)
                active_time_start = time.perf_counter()

            post_id = f"post_{post_index}"
            post_data = {
                "post_url": post_url,
                "post_id": post_id,
                "post_title": None,
                "post_images": [],
                "post_comments_gif": [],
            }
            self.config.data.post_entity_path = update_post_entity_path(self.config.data.post_entity_path, post_shortcode)
            # If using previously-captured requests to gather most media/metadata,
            # we only need to extract comments here. Skip other extraction blocks.
            if self.config.main.scrape_using_captured_requests:
                logger.debug(f"scrape_using_captured_requests=True — extracting comments only for {post_url}")
                try:
                    post_data["post_comments_gif"] = self._extract_comments_from_captured_requests(self.driver, self.config) or []
                    logger.debug(f"Captured-requests comment extraction returned {len(post_data['post_comments_gif'])} items for {post_url}")
                    # Active time: comment extraction
                    active_time_end = time.perf_counter()
                    active_time_accumulated += (active_time_end - active_time_start)
                except Exception as e:
                    logger.error(f"Captured-requests comment extraction failed for {post_url}: {e}")
                    logger.debug(traceback.format_exc())
                    # Active time: failed extraction attempt
                    active_time_end = time.perf_counter()
                    active_time_accumulated += (active_time_end - active_time_start)

                # Emit timing logs before returning
                total_time_end = time.perf_counter()
                total_time_ms = int((total_time_end - total_time_start) * 1000)
                active_time_ms = int(active_time_accumulated * 1000)
                if active_time_ms > total_time_ms:
                    active_time_ms = total_time_ms
                self._emit_timing_log("pipeline_total_time", "creator_content", creator_handle, content_id, total_time_ms, status, error_type)
                self._emit_timing_log("pipeline_active_time", "creator_content", creator_handle, content_id, active_time_ms, status, error_type)
                
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
                # Active time: title extraction
                active_time_end = time.perf_counter()
                active_time_accumulated += (active_time_end - active_time_start)
                active_time_start = time.perf_counter()
            except Exception as e:
                logger.error(f"Title extraction failed for {post_url}: {e}")
                logger.debug(traceback.format_exc())
                # Active time: failed extraction attempt
                active_time_end = time.perf_counter()
                active_time_accumulated += (active_time_end - active_time_start)
                active_time_start = time.perf_counter()

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
                    dl_result = write_and_run_full_download_script(
                        video_data_list,
                        self.config.data.media_path,
                        out_script_path="download_full_media.sh",
                        run_script=True,
                        redact_cookies=True,
                    )
                    logger.info(
                        f"Ran full-media download script for {len(video_data_list)} video(s): "
                        f"{dl_result.get('script_path')!r}"
                    )
                    post_data["video_download_tasks"].append(dl_result.get("script_path"))
                # Active time: media extraction
                active_time_end = time.perf_counter()
                active_time_accumulated += (active_time_end - active_time_start)
                active_time_start = time.perf_counter()
            except Exception as e:
                logger.error(f"Images extraction failed for {post_url}: {e}")
                logger.debug(traceback.format_exc())
                # Active time: failed extraction attempt
                active_time_end = time.perf_counter()
                active_time_accumulated += (active_time_end - active_time_start)
                active_time_start = time.perf_counter()
            # Likes / other sections
            try:
                post_data["likes"] = get_section_with_highest_likes(self.driver) or {}
                logger.info(f"Likes extraction successful for {post_url}")
                # Active time: likes extraction
                active_time_end = time.perf_counter()
                active_time_accumulated += (active_time_end - active_time_start)
                active_time_start = time.perf_counter()
            except Exception as e:
                logger.error(f"Likes extraction failed for {post_url}: {e}")
                logger.debug(traceback.format_exc())
                # Active time: failed extraction attempt
                active_time_end = time.perf_counter()
                active_time_accumulated += (active_time_end - active_time_start)
                active_time_start = time.perf_counter()
            
            # comments
            try:
                post_data["post_comments_gif"] = scrape_comments_with_gif(self.driver,self.config) or []
                # Active time: comments extraction
                active_time_end = time.perf_counter()
                active_time_accumulated += (active_time_end - active_time_start)
            except Exception as e:
                logger.error(f"Comments extraction with gif failed for {post_url}: {e}")
                logger.debug(traceback.format_exc())
                # Active time: failed extraction attempt
                active_time_end = time.perf_counter()
                active_time_accumulated += (active_time_end - active_time_start)

            return post_data, None

        except Exception as e:
            status = "error"
            error_type = type(e).__name__
            logger.exception(f"Unexpected error while scraping post {post_index} ({post_url}): {e}")
            error_data = {"index": post_index, "reason": str(e), "profile": self.config.main.target_profile}
            # Accumulate any remaining active time
            active_time_end = time.perf_counter()
            active_time_accumulated += (active_time_end - active_time_start)
            return None, error_data
        finally:
            # Calculate final timings
            total_time_end = time.perf_counter()
            total_time_ms = int((total_time_end - total_time_start) * 1000)
            active_time_ms = int(active_time_accumulated * 1000)
            
            # Ensure active_time <= total_time
            if active_time_ms > total_time_ms:
                active_time_ms = total_time_ms
            
            # Emit timing logs
            self._emit_timing_log("pipeline_total_time", "creator_content", creator_handle, content_id, total_time_ms, status, error_type)
            self._emit_timing_log("pipeline_active_time", "creator_content", creator_handle, content_id, active_time_ms, status, error_type)
            
            self._close_tab_and_switch_back(tab_handle, main_window_handle, debug)
            # Check if any windows are left open after closing.
            if not self.driver.window_handles:
                return None, None

    def scrape_posts_in_batches(self,
        post_elements,
        batch_size=3,
        save_every=5,
        tab_open_retries=4,
        debug=False,
        url_metadata=None
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
            url_metadata (dict, optional): Per-URL metadata overrides. Format:
                          {url: {"max_comments": N}}. Allows per-post control
                          of scraping parameters (e.g., max_comments override).

        Returns:
            A dictionary containing lists of 'scraped_posts' and 'skipped_posts'.
        """
        results = {"scraped_posts": [], "skipped_posts": []}
        total_scraped = 0

        main_handle = self.driver.current_window_handle
        tmp_file = self.config.data.tmp_path
        
        # Normalize url_metadata to empty dict if None (defensive)
        url_metadata = url_metadata or {}

        # main loop over batches
        for batch_start in range(0, len(post_elements), batch_size):
            time.sleep(random.uniform(1, 5))
            batch = post_elements[batch_start: batch_start + batch_size]
            opened = []  # list of tuples (index, href, handle)

            # --- open all posts in batch (in new tabs) ---
            for i, post_element in enumerate(batch, start=batch_start):
                time.sleep(random.uniform(1, 5))
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
                        logger.debug(f"Opened post {i+1} in new tab: {href} -> handle {new_handle}")
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
                time.sleep(random.uniform(3, 10))
                
                # SURGICAL OVERRIDE: Apply per-post max_comments if specified in url_metadata
                # Store original value to ensure proper restoration (even if exception occurs)
                original_max_comments = self.config.main.max_comments
                override_applied = False
                
                try:
                    # Extract shortcode from URL and check if it has metadata override
                    # url_metadata is now keyed by shortcode, not URL
                    post_shortcode = extract_instagram_shortcode(post_url)
                    if url_metadata and post_shortcode and post_shortcode in url_metadata:
                        metadata = url_metadata[post_shortcode]
                        override_max_comments = metadata.get("max_comments")
                        
                        if override_max_comments is not None:
                            # Validate override value (defensive check)
                            if isinstance(override_max_comments, int) and override_max_comments > 0:
                                logger.info(
                                    f"[Per-post override] {post_url} (shortcode: {post_shortcode}): "
                                    f"max_comments {original_max_comments} → {override_max_comments}"
                                )
                                self.config.main.max_comments = override_max_comments
                                override_applied = True
                            else:
                                logger.warning(
                                    f"[Per-post override] {post_url} (shortcode: {post_shortcode}): Invalid max_comments={override_max_comments}. "
                                    f"Using default: {original_max_comments}"
                                )
                    elif url_metadata and post_shortcode:
                        logger.debug(
                            f"[Per-post override] No metadata found for shortcode: {post_shortcode} (URL: {post_url})"
                        )
                    
                    # Scrape the post (existing code path)
                    post_data, error_data = self._scrape_and_close_tab(post_index, post_url, tab_handle, main_handle, debug)
                    
                finally:
                    # CRITICAL: Always restore original max_comments, even if exception occurs
                    if override_applied:
                        self.config.main.max_comments = original_max_comments
                        logger.debug(
                            f"[Per-post override] Restored max_comments to {original_max_comments}"
                        )

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

    def _emit_timing_log(self, event: str, category: str, creator_handle: str | None, content_id: str | None, duration_ms: int, status: str, error_type: str | None):
        """
        Emit a structured timing log event.
        
        Args:
            event: Either "pipeline_total_time" or "pipeline_active_time"
            category: Either "creator_profile" or "creator_content"
            creator_handle: Instagram profile handle
            content_id: Post/Reel ID or URL slug, or None for profile
            duration_ms: Duration in integer milliseconds
            status: "success" or "error"
            error_type: Exception class name or None
        """
        consumer_id = getattr(self.config.main, 'consumer_id', None)
        log_entry = {
            "event": event,
            "category": category,
            "creator_handle": creator_handle,
            "content_id": content_id,
            "pipeline": "Slug-Ig-Crawler",
            "duration_ms": duration_ms,
            "status": status,
            "error_type": error_type,
            "consumer_id": consumer_id,
            "thor_worker_id": self.thor_worker_id
        }
        logger.info(json.dumps(log_entry, ensure_ascii=False))

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



    def fire_human_scroll_signals(self, driver, container_selector: str, steps: int = 3):
        """
        Fires mouse + wheel-based scroll signals to trigger Instagram GraphQL.
        No clicking. No DOM mutation. No logic changes.
        Safe for Docker + headless.

        Call this AFTER your existing scroll logic.
        """

        js = r"""
        (function() {
            const container = document.querySelector(arguments[0]);
            if (!container) {
                return { ok: false, reason: "container not found" };
            }

            // Ensure focus
            container.tabIndex = -1;
            container.focus();

            // Mouse move to activate scroll listeners
            container.dispatchEvent(new MouseEvent("mousemove", {
                bubbles: true,
                clientX: Math.random() * container.clientWidth,
                clientY: Math.random() * container.clientHeight
            }));

            // Fire multiple wheel events (touchpad-like)
            for (let i = 0; i < arguments[1]; i++) {
                container.dispatchEvent(new WheelEvent("wheel", {
                    deltaY: 300 + Math.random() * 500,
                    bubbles: true,
                    cancelable: true
                }));
            }

            // Force layout / intersection checks
            container.getBoundingClientRect();

            // Visibility nudge (cheap but effective)
            document.dispatchEvent(new Event("visibilitychange"));

            return { ok: true };
        })();
        """

        result = driver.execute_script(js, container_selector, steps)
        time.sleep(random.uniform(0.4, 0.8))  # allow IG to emit GraphQL
        return result

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
        baseline_count = self.count_parsed_comments(config.data.post_entity_path)

        def get_valid_container(driver, max_retries=3):
            """Get a valid container selector with retry logic."""
            for attempt in range(max_retries):
                container_info = find_comment_container(driver)
                container = container_info.get("selector") if container_info else None
                
                if container:
                    # Validate the selector exists
                    try:
                        driver.find_element(By.CSS_SELECTOR, container)
                        logger.debug(f"Container selector validated successfully on attempt {attempt + 1}: {container}")
                        return container
                    except Exception as e:
                        logger.debug(f"Container selector invalid on attempt {attempt + 1}: {e}")
                        if attempt < max_retries - 1:
                            time.sleep(1)  # Wait before retry
                            continue
                
                # If no container found, try again
                if attempt < max_retries - 1:
                    logger.debug(f"No container found on attempt {attempt + 1}, retrying...")
                    time.sleep(1)
            
            logger.warning("Could not find valid container after retries")
            return None

        # Solution 3: Wait for comments to be present before finding container
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.html-div"))
            )
            logger.debug("Comments container detected, proceeding with container discovery")
        except Exception as e:
            logger.warning(f"Comments not loaded within timeout, proceeding anyway: {e}")

        # Solution 1: Get container with retry logic
        container = get_valid_container(driver)
        # Use fallback default selector if container discovery failed
        if not container:
            logger.warning("Container discovery failed, using fallback default selector")
            container = "div.html-div"
        self.reply_expander = ReplyExpander.with_container(driver, container, max_clicks=5, is_headless=self.config.main.headless, base_pause_ms=600)
        total_clicked = 0
        MAX_CLICKS_ALLOWED = 10
        total_clicked_texts = []
        all_logs = []
        batch_index = 0
        is_commentdata_saved = False
        # Initial extraction from embed script
        # this call doesnt get recorded into perf logs, as these first few comments are embedded in the HTML.
        initial_comments_data = extract_script_embedded_comments(self.driver)
        logger.debug(f"Initial embedded comments extraction returned {len(initial_comments_data.get('flattened_data', []))} items.")
        is_saved = self.config.main.registry.save_parsed_results(initial_comments_data, config.data.post_entity_path)
        if is_saved:
            is_commentdata_saved = True
        # self.config.main.registry.get_posts_data(self.config, self.config.data.post_page_data_key, data_type="post")
        prev_comment_count = 0
        end_comment_attempts = 0
        MAX_END_COMMENT_ATTEMPTS = config.main.comment_no_new_retries
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
                    break
                
            # result = self.reply_expander.expand_replies()
            if config.main.fetch_replies:
                result = self.reply_expander.expand_replies()
                # if self.config.main.headless:
                #     # 2️⃣ Frame sync — forces Chrome to flush layout + observers
                #     self.driver.execute_script(
                #         "return new Promise(r => requestAnimationFrame(() => r()));"
                #     )
                #     self.fire_human_scroll_signals(
                #         driver=self.driver,
                #         container_selector=container,
                #         steps=3
                #     )
            else:

                res = self.reply_expander.only_scroll(container, scroll_steps=30)
                # if self.config.main.headless:
                #     pass
                    # # 2️⃣ Frame sync — forces Chrome to flush layout + observers
                    # self.driver.execute_script(
                    #     "return new Promise(r => requestAnimationFrame(() => r()));"
                    # )
                    # self.fire_human_scroll_signals(
                    #     driver=self.driver,
                    #     container_selector=container,
                    #     steps=3
                    # )
                is_saved = self.config.main.registry.get_posts_data(
                    self.config,
                    self.config.data.post_page_data_key,
                    data_type="post"
                )

                after_count = self.count_parsed_comments(
                    self.config.data.post_entity_path
                )
                if (after_count - prev_comment_count == 0): # and (prev_comment_count != 0):
                    possible_end_of_comments = True
                    end_comment_attempts += 1
                prev_comment_count = after_count

                delta = after_count - baseline_count
                # batch_delta = delta - last_delta
                # last_delta = delta

                result = {
                    "clickedCount": delta,  # ← semantic progress
                    "clickedTexts": [],
                    "logs": [f"Scroll-only batch: +{delta} comments"],
                    "after_count": after_count,
                    "baseline_count": baseline_count,
                }
                logger.debug(result)
                if after_count >= config.main.max_comments:
                    logger.info(
                        f"Reached max_comments={config.main.max_comments} "
                        f"(current={after_count}). Stopping."
                    )
                    break
                if end_comment_attempts >= MAX_END_COMMENT_ATTEMPTS:
                # if res["idle_no_new_content"] == True:
                    logger.info(f"No new Comments found")
                    break

            clicked_count = result.get("clickedCount", 0)
            clicked_texts = result.get("clickedTexts", [])
            logs = result.get("logs", [])


            # --- PROGRESS / TERMINATION LOGIC ---
            if config.main.fetch_replies:
                # Reply-expansion mode: clicks are the progress signal
                if clicked_count == 0:
                    if self._handle_comment_load_error(driver, container):
                        # --- EXPONENTIAL COOLDOWN LOGIC ---
                        self.rate_limit_attempts += 1
                        base_min, base_max = 240, 360  # 4–6 minutes
                        multiplier = min(2 ** (self.rate_limit_attempts - 1), 16)
                        cooldown_seconds = random.uniform(base_min, base_max) * multiplier
                        # ----------------------------------

                        self.rate_limit_detected = True
                        self.rate_limit_reset_time = time.time() + cooldown_seconds
                        self._save_rate_limit_state()

                        logger.warning(
                            f"Rate limit triggered (attempt #{self.rate_limit_attempts}). "
                            f"Cooldown for {cooldown_seconds / 60:.1f} minutes "
                            f"(multiplier={multiplier}x)."
                        )
                        continue  # retry after cooldown
                    else:
                        # No clicks and no error → end of expandable replies
                        logger.info("No reply buttons clicked — end of reply expansion.")
                        break
            else:
                # Scroll-only mode: semantic progress already encoded in clicked_count
                # (clicked_count == number of newly saved comments)
                pass
                # if batch_delta <= 0:
                #     no_progress_batches += 1
                #     logger.info(
                #         f"No new comments in batch {batch_index} "
                #         f"({no_progress_batches}/{MAX_NO_PROGRESS_BATCHES})"
                #     )
                # else:
                #     no_progress_batches = 0

                # if no_progress_batches >= MAX_NO_PROGRESS_BATCHES:
                #     logger.info("No new comments after multiple batches — end of comments.")
                #     break


            all_logs.extend(logs)
            
            if config.main.fetch_replies:
                total_clicked += clicked_count
                total_clicked_texts.extend(clicked_texts)

                if total_clicked >= MAX_CLICKS_ALLOWED:
                    logger.info(
                        f"Reached max clicks allowed ({MAX_CLICKS_ALLOWED}). "
                        f"Final clicked count: {total_clicked}"
                    )
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
                logger.debug("Loaded persisted rate limit state from disk.")

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

    # def count_comments(self, path: str) -> int:
    #     if not Path(path).exists():
    #         return 0
    #     with open(path, "r", encoding="utf-8") as f:
    #         return sum(1 for _ in f)


    def count_parsed_comments(self, post_entity_path: str) -> int:
        seen = set()

        if not os.path.exists(post_entity_path):
            return 0

        with open(post_entity_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue

                parsed_models = record.get("parsed_models", [])
                if not parsed_models:
                    continue

                matched_keys = set(parsed_models[0].get("matched_keys", []))

                # 🚨 HARD FILTER: only comment models
                if not matched_keys & self.COMMENT_MODEL_KEYS:
                    continue

                for row in record.get("flattened_data", []):
                    cid = self.extract_comment_id(row)
                    if cid:
                        seen.add(cid)

        return len(seen)



    def extract_comment_id(self, row: dict) -> str | None:
        """
        Extract a stable COMMENT identifier from a flattened row.
        Only keys that clearly belong to comments are allowed.
        """
        for key, value in row.items():
            if not value:
                continue

            if self.COMMENT_ID_KEY_RE.search(key):
                return str(value)

        return None


    def _extract_ids_from_parsed_data(self, parsed_data) -> set[str]:
        ids = set()
        for row in parsed_data.get("flattened_data", []):
            cid = self.extract_comment_id(row)
            if cid:
                ids.add(cid)
        return ids



    def _screenshot_worker(self, interval_sec=7):
        out_dir = Path(self.config.data.shot_dir).expanduser().resolve()
        out_dir.mkdir(parents=True, exist_ok=True)

        logger.debug(f"[screenshot] resolved out_dir = {out_dir}")

        while not self.screenshot_stop_event.is_set():
            try:
                ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                path = out_dir / f"shot_{ts}.webp"

                # Capture PNG bytes from Selenium
                png_bytes = self.driver.get_screenshot_as_png()

                # Decode and re-encode as WebP
                img = Image.open(BytesIO(png_bytes))

                img.save(
                    path,
                    format="WEBP",
                    quality=78,      # sweet spot: big savings, visually sane
                    method=2         # slowest = best compression
                )

                logger.debug(f"[screenshot] saved path={path}")

            except Exception as e:
                logger.debug(f"[screenshot] worker error: {e}")

            self.screenshot_stop_event.wait(interval_sec)


