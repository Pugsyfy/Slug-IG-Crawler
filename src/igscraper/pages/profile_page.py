import random,pdb
from .base_page import BasePage
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
import time, logging
from typing import List
from selenium.webdriver.support.ui import WebDriverWait

from igscraper.utils import HumanScroller, scrape_comments_with_gif,scroll_with_mouse,random_delay,capture_instagram_requests
from igscraper.logger import get_logger
from typing import List
from selenium.common.exceptions import WebDriverException, StaleElementReferenceException

logger = get_logger(__name__)
# TODO: These selectors are fragile and may need frequent updates
# This selector is more robust. It looks for any link within the main content
# area that has a URL path starting with /p/, which is characteristic of post links.
POST_SELECTOR = (By.CSS_SELECTOR, "main a[href^='/p/']")
POST_MODAL_SELECTOR = (By.CSS_SELECTOR, "div[role='dialog']")

class ProfilePage(BasePage):
    """
    Represents an Instagram profile page and provides methods for interacting with it.

    This page object handles navigation, scrolling to load content, and collecting
    post elements from a user's profile.
    """
    def __init__(self, driver, config):
        """
        Initializes the ProfilePage object.

        Args:
            driver: The Selenium WebDriver instance.
            config: The application's configuration object.
        """
        super().__init__(driver)
        self.config = config
        self.scroller = HumanScroller(self.driver)

    def navigate_to_profile(self, handle: str) -> None:
        """
        Navigates the browser to a specific Instagram profile page.

        Args:
            handle: The Instagram username of the profile to open.
        """
        url = f"https://www.instagram.com/{handle}/"
        self.driver.get(url)
        self.wait_for_sections()

    def get_visible_post_elements(self) -> List[WebElement]:
        """
        Finds and returns all currently visible post elements on the page.

        It locates the rows of posts and extracts the individual post links (<a> tags) from them.
        """
        xpath_for_class = "//*[@class and contains(concat(' ', @class, ' '), ' _ac7v ')]"

        # Instagram has posts in groups of 3 on the handle page.
        # each elements_with_class_xpath has 3 posts inside it
        elements_with_class_xpath = self.driver.find_elements(By.XPATH, xpath_for_class)
        logging.info(f"Found {len(elements_with_class_xpath)} elements with class _ac7v")
        ## flatten to get all posts
        all_href_elem = [row.find_elements(By.CSS_SELECTOR, "a") for row in elements_with_class_xpath]
        all_href_elem = [elem for sublist in all_href_elem for elem in sublist]  # flatten the list
        return all_href_elem

    def scroll_and_collect_(self, limit: int) -> List[str]:
        """
        Scrolls down the profile page and collects unique post URLs.

        This method repeatedly scrolls the page to trigger the loading of more posts.
        After each scroll, it collects the URLs of the visible posts, ensuring no
        duplicates are added. The process stops when the desired limit is reached
        or when no new posts are loaded after several retries.

        Args:
            limit: The target number of post URLs to collect.

        Returns:
            A list of unique post URL strings.
        """
        posts = []
        last_height = self.driver.execute_script("return document.body.scrollHeight")
        retries = 0
        is_data_saved = False
        try:
            while len(posts) < limit:
                try:
                    new_posts = self.get_visible_post_elements()
                    for post in new_posts:
                        try:
                            href = post.get_attribute("href")
                            if href and href not in posts:
                                posts.append(href)
                                if len(posts) >= limit:
                                    break
                        except StaleElementReferenceException:
                            logger.debug("Skipped stale element while extracting href.")
                            continue

                    # scroll_with_mouse(self, steps=4)
                    self.scroller.perform(4)
                    if len(posts) % 12 == 0 and len(posts) != 0:
                        is_saved = self.config.main.registry.get_posts_data(self.config, self.config.data.profile_page_data_key, data_type="profile")
                        if is_saved:
                            is_data_saved = True

                    new_height = self.driver.execute_script("return document.body.scrollHeight")
                    if new_height == last_height:
                        retries += 1
                        random_delay(1,2)
                        if retries >= self.config.main.page_scroll_retries:
                            logger.warning("No new posts found, stopping scroll.")
                            break
                    else:
                        retries = 0
                    last_height = new_height
                except WebDriverException as e:
                    logger.error(f"Selenium error during scroll: {e}")
                    break

        except Exception as e:
            logger.exception(f"Unexpected error in scroll_and_collect: {e}")
            return False, []

        finally:
            is_saved = self.config.main.registry.get_posts_data(self.config, self.config.data.profile_page_data_key, data_type="profile")
            # if is_saved or is_data_saved:
                # logger.info("Profile page data was saved. Trying to push to gs bucket")
                # self.backend.on_posts_batch_ready(self.config.data.profile_path)
            logger.info(f"Collected {len(posts)} post URLs.")
            return (is_data_saved or is_saved), posts

    def open_post_element(self, post_element: WebElement) -> None:
        """
        Clicks a post element to open the post in a modal dialog.

        Args:
            post_element: The WebElement corresponding to the post link to be clicked.
        """
        self.click(post_element)
        self.find(POST_MODAL_SELECTOR)  # Wait for modal to open


    def extract_comments(self, steps):
        """
        Extracts comments from the currently open post modal.

        Args:
            steps: The number of scroll steps to perform while collecting comments.

        Returns:
            A list of dictionaries, where each dictionary contains data for one comment.
        """
        # return human_scroll_and_scrape_comments(self.driver)
        if steps:
            return scrape_comments_with_gif(self.driver, steps=steps)
        return scrape_comments_with_gif(self.driver)

    def wait_for_sections(self, min_sections: int = 2, timeout: int = 10):
        """
        Waits until a minimum number of <section> elements are present in the DOM.

        This is used as a signal that the main content of the profile page has loaded.

        Args:
            min_sections: The minimum number of <section> tags to wait for.
            timeout: The maximum time in seconds to wait.
        """
        wait = WebDriverWait(self.driver, timeout)
        return wait.until(
            lambda d: len(d.find_elements(By.TAG_NAME, "section")) >= min_sections
        )

    # def collect_post_urls_data(self):