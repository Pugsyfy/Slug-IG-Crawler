"""
Main pipeline for the Instagram Profile Scraper.

This module orchestrates the entire scraping process, from loading the configuration
to initializing the backend, collecting post URLs, and scraping them in batches.
"""
import datetime
import os,sys
import copy
import random
import traceback
import time
import json
from .config import load_config, expand_paths, Config, ProfileTarget
from .backends import SeleniumBackend
from .logger import get_logger
from pathlib import Path
from .models.registry_parser import GraphQLModelRegistry
from .models.common import MODEL_REGISTRY
from .utils import capture_instagram_requests
import pdb 
logger = get_logger(__name__)

def attach_debugger_if_needed():
    if os.environ.get("DEBUG_ATTACH") == "1":
        import debugpy
        debugpy.listen(("0.0.0.0", 5678))
        print("🟢 Waiting for debugger attach on :5678")
        debugpy.wait_for_client()

class Pipeline:
    """
    Orchestrates the entire scraping process.

    This class initializes the backend and configuration, manages the browser
    lifecycle, and iterates through target profiles to scrape them sequentially.
    """

    def __init__(self, config_path: str, dry_run: bool = False):
        """
        Initializes the Pipeline.

        Args:
            config_path: The file path to the TOML configuration file.
            dry_run: A boolean flag for test runs (not currently implemented).
        """
        self.master_config = load_config(config_path)  # Keep this pristine
        self.config = None
        self.dry_run = dry_run
        
        # Store thor_worker_id from config once at initialization
        self.thor_worker_id = self.master_config.trace.thor_worker_id
        
        self.backend = SeleniumBackend(self.master_config)
        
        # Make thor_worker_id available on backend for SQL inserts and logging
        self.backend.thor_worker_id = self.thor_worker_id
        # Also set on FileEnqueuer for SQL inserts
        self.backend._enqueuer.thor_worker_id = self.thor_worker_id
        
        self.all_results = {}
        self.registry = GraphQLModelRegistry(MODEL_REGISTRY, self.master_config.data.schema_path)
        self.master_config.main.registry = self.registry

    def _scrape_single_profile(self, profile_target: ProfileTarget) -> dict:
        """
        Handles the scraping logic for a single profile using the shared browser session.

        Args:
            profile_target: The configuration object for the target profile.

        Returns:
            A dictionary containing the scraping results for this profile.
        """
        profile_name = profile_target.name
        num_posts_to_scrape = profile_target.num_posts
        results = {"scraped_posts": [], "skipped_posts": []}
        datetime_now = datetime.datetime.now().strftime("%Y%m%d_%H%M")
        logger.info(f"--- Starting scrape for single profile: {profile_name} and num_posts: {num_posts_to_scrape} and datetime: {datetime_now} ---")

        # Timing: Start total time (wall clock)
        total_time_start = time.perf_counter()
        active_time_start = time.perf_counter()
        active_time_accumulated = 0.0
        error_type = None
        status = "success"

        try:
            # Create a profile-specific config by copying the base and updating it
            # deepcopy_config = copy.deepcopy(self.config)
            driver_obj_ref = self.master_config._driver
            self.master_config._driver = None
            self.config = copy.deepcopy(self.master_config)
            self.config._driver = driver_obj_ref
            self.master_config._driver = driver_obj_ref
            self.config.main.target_profile = profile_name # Needed for path expansion
            # substitutions = {"target_profile": profile_name}
            substitutions = {"date": datetime_now.split('_')[0], "datetime": datetime_now}
            expand_paths(self.config, substitutions)
            # pdb.set_trace()
            logger.info(self.config)
            # Update the backend's config and expand paths for the current profile
            self.backend.config = self.config
            self.backend.profile_page.config = self.config
            self.backend.start_screenshot_worker()
            
            # Active time: open_profile
            active_time_end = time.perf_counter()
            active_time_accumulated += (active_time_end - active_time_start)
            self.backend.open_profile(profile_name)
            active_time_start = time.perf_counter()
            
            path = Path(self.config.data.output_dir) / profile_name
            path.parent.mkdir(parents=True, exist_ok=True)
            logger.info(f"Path created - {path}")
            
            # Active time: get_post_elements
            active_time_end = time.perf_counter()
            active_time_accumulated += (active_time_end - active_time_start)
            post_elements = self.backend.get_post_elements(num_posts_to_scrape)
            active_time_start = time.perf_counter()

            if not post_elements:
                logger.warning(f"No new posts to scrape for profile {profile_name}. Skipping.")
                # Still emit timing logs even if no posts
                active_time_end = time.perf_counter()
                active_time_accumulated += (active_time_end - active_time_start)
                total_time_end = time.perf_counter()
                total_time_ms = int((total_time_end - total_time_start) * 1000)
                active_time_ms = int(active_time_accumulated * 1000)
                
                # Emit timing logs
                self._emit_timing_log("pipeline_total_time", "creator_profile", profile_name, None, total_time_ms, status, error_type)
                self._emit_timing_log("pipeline_active_time", "creator_profile", profile_name, None, active_time_ms, status, error_type)
                return results

            batch_size = self.config.main.batch_size
            if self.config.main.randomize_batch:
                batch_size = random.randint(batch_size, batch_size + 4)

            if self.config.main.fetch_comments:
                # Active time: scrape_posts_in_batches (this will track its own active time internally)
                active_time_end = time.perf_counter()
                active_time_accumulated += (active_time_end - active_time_start)
                results = self.backend.scrape_posts_in_batches(
                    post_elements, batch_size=batch_size, save_every=self.config.main.save_every
                )
                active_time_start = time.perf_counter()
            
            # Final active time accumulation
            active_time_end = time.perf_counter()
            active_time_accumulated += (active_time_end - active_time_start)
            logger.info(f"Pipeline completed for profile {profile_name}.")

        except Exception as e:
            status = "error"
            error_type = type(e).__name__
            logger.critical(f"Pipeline for profile '{profile_name}' failed with an error: {e}")
            logger.debug(traceback.format_exc())
            # Accumulate any remaining active time
            active_time_end = time.perf_counter()
            active_time_accumulated += (active_time_end - active_time_start)
        finally:
            # Calculate final timings
            total_time_end = time.perf_counter()
            total_time_ms = int((total_time_end - total_time_start) * 1000)
            active_time_ms = int(active_time_accumulated * 1000)
            
            # Ensure active_time <= total_time
            if active_time_ms > total_time_ms:
                active_time_ms = total_time_ms
            
            # Emit timing logs
            self._emit_timing_log("pipeline_total_time", "creator_profile", profile_name, None, total_time_ms, status, error_type)
            self._emit_timing_log("pipeline_active_time", "creator_profile", profile_name, None, active_time_ms, status, error_type)
        
        return results

    def _scrape_from_url_file(self) -> dict:
        """
        Handles the scraping logic for a list of URLs provided in a file.
        """

        # 1. Resolve run name
        run_name = self.master_config.main.run_name_for_url_file
        if not run_name:
            logger.error("run_name_for_url_file must be set for URL mode")
            return {}

        datetime_now = datetime.datetime.now().strftime("%Y%m%d_%H%M")

        # 2. Clone config exactly like mode-1
        driver_obj_ref = self.master_config._driver
        self.master_config._driver = None
        run_config = copy.deepcopy(self.master_config)
        run_config._driver = driver_obj_ref
        self.master_config._driver = driver_obj_ref

        # 3. Set target_profile + expand paths
        run_config.main.target_profile = run_name
        substitutions = {
            "date": datetime_now.split('_')[0],
            "datetime": datetime_now,
        }
        expand_paths(run_config, substitutions)

        logger.info(f"--- Starting URL file scrape for run: {run_name} ---")

        # 4. Rebind backend exactly like mode-1
        self.backend.config = run_config
        self.backend.profile_page.config = run_config
        self.backend.start_screenshot_worker()

        # 5. Read URL file from *expanded* path
        urls_filepath = run_config.data.urls_filepath
        logger.info(f"[Mode 2] Using URL file: {urls_filepath}")
        try:
            with open(urls_filepath, "r", encoding="utf-8") as f:
                post_urls = [line.strip() for line in f if line.strip()]
            logger.info(f"Read {len(post_urls)} URLs from {urls_filepath}.")
            logger.info(f"[Mode 2] URL file contents:\n" + "\n".join(f"  - {url}" for url in post_urls))
        except FileNotFoundError:
            logger.error(f"URL file not found at: {urls_filepath}")
            return {}

        if not post_urls:
            return {"scraped_posts": [], "skipped_posts": []}

        # 6. Filter already-processed URLs (critical)
        # processed = self.backend._load_processed_urls(run_config.data.metadata_path)
        # urls_to_scrape = [u for u in post_urls if u not in processed]
        urls_to_scrape = post_urls
        if not urls_to_scrape:
            logger.info("No new URLs to scrape after filtering.")
            return {"scraped_posts": [], "skipped_posts": []}

        # 7. Batch size logic (unchanged)
        batch_size = run_config.main.batch_size
        if run_config.main.randomize_batch:
            batch_size = random.randint(batch_size, batch_size + 4)

        # 8. Scrape using the SAME backend path as mode-1
        return self.backend.scrape_posts_in_batches(
            urls_to_scrape,
            batch_size=batch_size,
            save_every=run_config.main.save_every
        )

    def run(self) -> dict:
        """
        Executes the main scraping pipeline for all configured target profiles.

        It starts the browser, iterates through each profile, scrapes it, and
        then closes the browser session upon completion.

        Returns:
            A dictionary containing the aggregated results for all profiles.
        """
        try:
            self.backend.start()
            attach_debugger_if_needed()
            self.master_config._driver = self.backend.driver
            logger.info(f"Master config: {self.master_config}")
            # Startup log with thor_worker_id
            logger.info(f"igscraper start | thor_worker_id={self.thor_worker_id}")
            # Check which mode to run in
            if self.master_config.data.urls_filepath and os.path.exists(self.master_config.data.urls_filepath):
                # Mode 2: Scrape from a URL file
                self.master_config.main.mode = 2
                run_name = self.master_config.main.run_name_for_url_file
                self.all_results[run_name] = self._scrape_from_url_file()
            elif self.master_config.main.target_profiles:
                # Mode 1: Scrape target profiles
                self.master_config.main.mode = 1
                for profile_target in self.master_config.main.target_profiles:
                    logger.info(f"--- Starting scrape for profile: {profile_target.name} ---")
                    self.all_results[profile_target.name] = self._scrape_single_profile(profile_target)
            else:
                logger.warning("No target profiles or valid URL file provided in the configuration. Nothing to do.")
        except Exception as e:
            logger.critical(f"A critical error occurred during pipeline setup or teardown: {e}")
            logger.debug(traceback.format_exc())
        finally:
            import threading
            print("THREADS AT EXIT:")
            for t in threading.enumerate():
                print(t.name, "daemon=", t.daemon)
            # Stop the backend once after all profiles are processed
            if self.backend:
                self.backend.stop()
                logger.info("Browser has been closed.")
            os._exit(0)

        return self.all_results

    def _emit_timing_log(self, event: str, category: str, creator_handle: str, content_id: str | None, duration_ms: int, status: str, error_type: str | None):
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
        consumer_id = getattr(self.config.main, 'consumer_id', None) if self.config else None
        log_entry = {
            "event": event,
            "category": category,
            "creator_handle": creator_handle,
            "content_id": content_id,
            "pipeline": "igscraper",
            "duration_ms": duration_ms,
            "status": status,
            "error_type": error_type,
            "consumer_id": consumer_id,
            "thor_worker_id": self.thor_worker_id
        }
        logger.info(json.dumps(log_entry, ensure_ascii=False))

def run_pipeline(config_path: str, dry_run: bool = False):
    """Legacy function wrapper to instantiate and run the Pipeline class."""
    pipeline = Pipeline(config_path, dry_run)
    return pipeline.run()