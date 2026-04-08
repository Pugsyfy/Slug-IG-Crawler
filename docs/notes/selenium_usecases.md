# Selenium Usage Patterns in Instagram Profile Scraper

This document provides a comprehensive analysis of how Selenium is used throughout the codebase, including WebDriver management, network request/response capturing, JavaScript execution, and security measures.

## Table of Contents

1. [Selenium Package Imports and Dependencies](#selenium-package-imports-and-dependencies)
2. [SeleniumBackend Class](#seleniumbackend-class)
3. [WebDriver Initialization and Configuration](#webdriver-initialization-and-configuration)
4. [Network Request/Response Capturing](#network-requestresponse-capturing)
5. [Chrome DevTools Protocol (CDP) Usage](#chrome-devtools-protocol-cdp-usage)
6. [JavaScript Execution Patterns](#javascript-execution-patterns)
7. [Security and Monitoring](#security-and-monitoring)
8. [Page Object Model Implementation](#page-object-model-implementation)
9. [Performance Logging](#performance-logging)
10. [Common Patterns and Utilities](#common-patterns-and-utilities)

---

## Selenium Package Imports and Dependencies

### Primary Selenium Imports

The codebase uses multiple Selenium modules across different files:

**`src/igscraper/backends/selenium_backend.py`:**
```python
from selenium import webdriver
from seleniumwire import webdriver  # Network interception
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
```

**`src/igscraper/utils.py`:**
```python
from selenium.webdriver import ActionChains
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    ElementClickInterceptedException,
    WebDriverException,
    JavascriptException
)
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.common.keys import Keys
```

**`src/igscraper/pages/base_page.py`:**
```python
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
```

**`src/igscraper/pages/profile_page.py`:**
```python
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import WebDriverException, StaleElementReferenceException
```

### Key Dependencies

- **selenium**: Core WebDriver automation
- **seleniumwire**: Network request interception (imported but may not be actively used)
- **webdriver-manager**: Automatic ChromeDriver management

---

## SeleniumBackend Class

### Class Location
`src/igscraper/backends/selenium_backend.py`

### Purpose
The `SeleniumBackend` class is the primary interface for browser automation. It implements the `Backend` abstract base class and manages the entire WebDriver lifecycle.

### Key Responsibilities

1. **WebDriver Lifecycle Management**
   - Initialization (`start()`)
   - Cleanup (`stop()`)
   - Tab/window management

2. **Authentication**
   - Cookie-based login via `_login_with_cookies()`

3. **Navigation**
   - Profile page navigation
   - Post URL collection
   - Tab opening and switching

4. **Data Extraction**
   - Post metadata extraction
   - Comment collection
   - Media URL extraction

5. **Network Monitoring**
   - Performance log capture
   - GraphQL request interception

### Key Methods

#### `start()`
Initializes Chrome WebDriver with anti-detection settings:

```python
def start(self):
    options = Options()
    # Performance logging for network capture
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    perf_log_prefs = {"enableNetwork": True}
    options.set_capability("goog:perfLoggingPrefs", perf_log_prefs)
    
    # Anti-detection settings
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    
    # Initialize driver
    service = Service(ChromeDriverManager().install())
    self.driver = webdriver.Chrome(service=service, options=options)
    self.driver = patch_driver(self.driver)  # Security patching
    
    # Hide webdriver property
    self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    
    # Setup network tracking
    self.setup_network()
    self._login_with_cookies()
    self.profile_page = ProfilePage(self.driver, self.config)
```

#### `setup_network()`
Enables Chrome DevTools Protocol for network monitoring:

```python
def setup_network(self):
    # Enable network tracking
    self.driver.execute_cdp_cmd("Network.enable", {})
    self.driver.execute_cdp_cmd("Network.clearBrowserCache", {})
    self.driver.execute_cdp_cmd("Network.clearBrowserCookies", {})
    self.driver.set_script_timeout(180)
    self.driver.command_executor.set_timeout(300)
```

#### `_login_with_cookies()`
Authenticates using saved cookies:

```python
def _login_with_cookies(self):
    self.driver.get("https://www.instagram.com/")  # Must visit domain first
    with open(self.config.data.cookie_file, "rb") as f:
        cookies = pickle.load(f)
    for cookie in cookies:
        if 'expiry' in cookie and isinstance(cookie['expiry'], float):
            cookie['expiry'] = int(cookie['expiry'])
        self.driver.add_cookie(cookie)
    self.driver.refresh()  # Apply cookies
```

#### `scrape_posts_in_batches()`
Manages batch processing of posts with tab management:

```python
def scrape_posts_in_batches(self, post_elements, batch_size=3, save_every=5, ...):
    main_handle = self.driver.current_window_handle
    for batch_start in range(0, len(post_elements), batch_size):
        # Open posts in new tabs
        for post_element in batch:
            new_handle = self.open_href_in_new_tab(href, tab_open_retries)
            opened.append((i, href, new_handle))
        
        # Scrape each tab
        for post_index, post_url, tab_handle in opened:
            post_data, error_data = self._scrape_and_close_tab(...)
            # Save intermediate results
            save_intermediate(post_data, tmp_file)
```

#### `open_href_in_new_tab()`
Opens URLs in new browser tabs:

```python
def open_href_in_new_tab(self, href, tab_open_retries):
    before_handles = set(self.driver.window_handles)
    # Open new tab with JavaScript
    self.driver.execute_script("window.open(arguments[0], '_blank');", href)
    # Wait for new handle to appear
    for _ in range(tab_open_retries):
        after_handles = set(self.driver.window_handles)
        diff = after_handles - before_handles
        if diff:
            return diff.pop()
        time.sleep(0.5 + random.random() * 0.5)
```

---

## WebDriver Initialization and Configuration

### Chrome Options Configuration

The codebase configures Chrome with extensive anti-detection and logging settings:

**Anti-Detection Settings:**
```python
options = Options()
options.add_argument("--disable-blink-features=AutomationControlled")
options.add_experimental_option("excludeSwitches", ["enable-automation"])
options.add_experimental_option('useAutomationExtension', False)
options.add_argument("--autoplay-policy=no-user-gesture-required")
options.add_argument("--disable-background-timer-throttling")
options.add_argument("--disable-renderer-backgrounding")
options.add_argument("--disable-backgrounding-occluded-windows")
```

**Performance Logging:**
```python
options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
perf_log_prefs = {"enableNetwork": True}
options.set_capability("goog:perfLoggingPrefs", perf_log_prefs)
```

**Window Configuration:**
```python
options.add_argument("--window-size=1920,1080")
options.add_argument("--start-maximized")
if self.config.main.headless:
    options.add_argument("--headless=new")
```

**User Agent:**
```python
user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36"
options.add_argument(f'user-agent={user_agent}')
```

### WebDriver Manager Integration

Automatic ChromeDriver management using `webdriver-manager`:

```python
from webdriver_manager.chrome import ChromeDriverManager

try:
    service = Service(ChromeDriverManager().install())
    self.driver = webdriver.Chrome(service=service, options=options)
except Exception as e:
    logger.error(f"Failed to initialize Chrome driver with webdriver-manager: {e}")
    # Fallback to default initialization
    self.driver = webdriver.Chrome(options=options)
```

---

## Network Request/Response Capturing

### Performance Log Capture

The codebase extensively uses Chrome's performance logs to capture network requests and responses.

#### `capture_instagram_requests()` - Primary Capture Function

**Location:** `src/igscraper/utils.py:4417`

**Purpose:** Captures Instagram API and GraphQL requests from Chrome performance logs.

**Implementation:**
```python
def capture_instagram_requests(driver, limit: int = 5000):
    """
    Capture all instagram.com requests that include keywords: api, graphql, v1.
    Returns a list of dicts: {requestId, url, request, response}.
    """
    results = []
    keywords = ["api/v1", "graphql/query"]
    
    # Grab performance logs from Chrome
    logs = driver.get_log("performance")
    for entry in logs:
        try:
            msg = json.loads(entry["message"])["message"]
            method = msg.get("method", "")
            params = msg.get("params", {})
            
            # Collect request events
            if method == "Network.requestWillBeSent":
                url = params["request"]["url"]
                if "instagram.com/" in url and any(k in url for k in keywords):
                    results.append({
                        "requestId": params["requestId"],
                        "url": url,
                        "request": params["request"],
                        "response": None
                    })
            
            # Collect response events + body
            elif method == "Network.responseReceived":
                url = params["response"]["url"]
                if "instagram.com/" in url and any(k in url for k in keywords):
                    req_id = params["requestId"]
                    try:
                        # Fetch response body via CDP
                        body = driver.execute_cdp_cmd(
                            "Network.getResponseBody", {"requestId": req_id}
                        )
                        response_body = body.get("body", None)
                    except Exception as e:
                        response_body = f"Error fetching body: {e}"
                    
                    results.append({
                        "requestId": req_id,
                        "url": url,
                        "request": None,
                        "response": response_body
                    })
        except Exception:
            continue
    
    # Merge requests + responses by requestId
    merged = {}
    for r in results:
        rid = r["requestId"]
        if rid not in merged:
            merged[rid] = {"requestId": rid, "url": r["url"], "request": None, "response": None}
        if r["request"]:
            merged[rid]["request"] = r["request"]
        if r["response"]:
            merged[rid]["response"] = r["response"]
    
    return list(merged.values())[:limit]
```

**Key Features:**
- Filters requests by keywords: `"api/v1"`, `"graphql/query"`
- Captures both request and response data
- Uses CDP `Network.getResponseBody` to fetch response bodies
- Merges request and response events by `requestId`

#### `get_shortcode_web_info()` - GraphQL Response Extraction

**Location:** `src/igscraper/utils.py:4316`

**Purpose:** Extracts GraphQL responses containing 'data' from performance logs.

**Implementation:**
```python
def get_shortcode_web_info(driver) -> List[Dict[str, Any]]:
    """
    Extract Instagram GraphQL responses that contain 'data'.
    Returns list of {requestId, url, data, data_keys, status, extensions}.
    """
    results = []
    logs = driver.get_log("performance")
    
    for entry in logs:
        try:
            log = json.loads(entry["message"])["message"]
            
            if log["method"] == "Network.responseReceived":
                request_id = log["params"]["requestId"]
                response = log["params"]["response"]
                url = response["url"]
                
                headers = {k.lower(): v for k, v in response.get("headers", {}).items()}
                content_type = headers.get("content-type", "")
                
                if "json" not in content_type:
                    continue
                
                # Fetch response body via CDP
                body_dict = driver.execute_cdp_cmd(
                    "Network.getResponseBody", {"requestId": request_id}
                )
                body = body_dict.get("body")
                
                if body:
                    data = json.loads(body)
                    if isinstance(data, dict) and "data" in data:
                        data_keys = list(data["data"].keys())[:2]
                        results.append({
                            "requestId": request_id,
                            "url": url,
                            "data": data["data"],
                            "data_keys": data_keys,
                            "status": data.get("status"),
                            "extensions": data.get("extensions"),
                        })
        except Exception:
            continue
    
    return results
```

#### `list_logged_urls()` - URL Listing Utility

**Location:** `src/igscraper/utils.py:4387`

**Purpose:** Lists all network response URLs from performance logs for debugging.

**Implementation:**
```python
def list_logged_urls(driver, limit: int = 5000):
    """
    List all logged network response URLs from performance logs.
    Helps debug whether /graphql/query requests are captured.
    """
    logs = driver.get_log("performance")
    urls = []
    
    for entry in logs:
        try:
            log = json.loads(entry["message"])["message"]
            if log["method"] == "Network.responseReceived":
                response = log["params"]["response"]
                url = response["url"]
                urls.append([url, response])
        except Exception:
            continue
    
    graphql_urls = [[u, r] for u, r in urls if '/graphql/query' in u]
    return urls, graphql_urls
```

#### `find_audio_for_videos()` - Media Resource Detection

**Location:** `src/igscraper/utils.py:3327`

**Purpose:** Finds matching audio/mp4 requests in performance logs for video resources.

**Implementation:**
```python
def find_audio_for_videos(driver, video_results):
    """
    Try to find a matching audio/mp4 request in the Selenium performance logs.
    """
    logs = driver.get_log("performance")
    audio_map = {}
    
    for entry in logs:
        try:
            msg = json.loads(entry["message"])["message"]
            if msg.get("method") != "Network.responseReceived":
                continue
            resp = msg["params"]["response"]
            url = resp.get("url", "")
            mime = resp.get("mimeType", "")
            if mime == "audio/mp4":
                fn_match = url.split("/")[-1].split("?")[0]
                audio_map[fn_match] = url
        except Exception:
            continue
    
    # Match audio URLs to video results
    results = []
    for video in video_results:
        filename = video["filename"]
        base = filename.replace(".mp4", "")
        audio_url = None
        for cand_fn, cand_url in audio_map.items():
            if base in cand_fn:
                audio_url = cand_url
                break
        # Add audio URL to video result
        if audio_url:
            video["audio"] = {"url": audio_url, ...}
    
    return results
```

### Usage in GraphQL Model Registry

**Location:** `src/igscraper/models/registry_parser.py:891`

The `GraphQLModelRegistry` uses `capture_instagram_requests()` to extract GraphQL data:

```python
def get_posts_data(self, config, keys_to_match: List[str], data_type: str = "post"):
    # Capture network requests
    relevant_requests_data = capture_instagram_requests(config._driver, 500)
    
    # Extract GraphQL keys
    graphql_keys = self.extract_graphql_data_keys(relevant_requests_data)
    
    # Parse responses
    parsed_results = self.parse_responses(relevant_requests_data, keys_to_match, config._driver)
    
    # Save parsed results
    self.save_parsed_results(parsed_results, save_path)
```

---

## Chrome DevTools Protocol (CDP) Usage

### CDP Commands Used

#### Network Domain

**`Network.enable`**
```python
self.driver.execute_cdp_cmd("Network.enable", {})
```
Enables network domain events for monitoring.

**`Network.clearBrowserCache`**
```python
self.driver.execute_cdp_cmd("Network.clearBrowserCache", {})
```
Clears browser cache.

**`Network.clearBrowserCookies`**
```python
self.driver.execute_cdp_cmd("Network.clearBrowserCookies", {})
```
Clears browser cookies.

**`Network.getResponseBody`**
```python
body_dict = driver.execute_cdp_cmd(
    "Network.getResponseBody", {"requestId": request_id}
)
response_body = body_dict.get("body", None)
```
Fetches the response body for a specific network request by `requestId`. This is the primary method for extracting response data from captured network requests.

### CDP Event Monitoring

The codebase monitors CDP events through Chrome's performance logs:

1. **`Network.requestWillBeSent`**: Captured when a request is about to be sent
2. **`Network.responseReceived`**: Captured when a response is received

These events are accessed via:
```python
logs = driver.get_log("performance")
for entry in logs:
    msg = json.loads(entry["message"])["message"]
    method = msg.get("method", "")  # e.g., "Network.responseReceived"
    params = msg.get("params", {})  # Contains request/response details
```

---

## JavaScript Execution Patterns

### Common JavaScript Execution Methods

#### `execute_script()` - Synchronous JavaScript

Used extensively throughout the codebase for:
- DOM manipulation
- Data extraction
- Element interaction
- Browser property modification

**Examples:**

**Hide WebDriver Property:**
```python
self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
```

**Open New Tab:**
```python
self.driver.execute_script("window.open(arguments[0], '_blank');", href)
```

**Scroll Element Into View:**
```python
driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
```

**Get Element Bounding Rect:**
```python
rect = driver.execute_script(
    "const r=arguments[0].getBoundingClientRect();"
    "return {cx: Math.round(r.left + r.width/2), cy: Math.round(r.top + r.height/2)};",
    element,
)
```

**Extract Post Title Data:**
```python
js_code = f"""
function getPostTitleData(variableA) {{
    const divs = Array.from(document.querySelectorAll('div'));
    // ... complex DOM traversal logic ...
    return data;
}}
return getPostTitleData({href_string_js});
"""
result = self.driver.execute_script(js_code)
```

**Get Performance Entries:**
```python
js = """
const resources = performance.getEntriesByType("resource")
    .filter(e => e.name && e.name.includes(".mp4"));
return resources.map(e => ({
    url: e.name,
    transferSize: e.transferSize || 0,
    // ... more properties
}));
"""
mp4_resources = driver.execute_script(js)
```

#### `execute_async_script()` - Asynchronous JavaScript

Used in `ReplyExpander` for async operations:

**Location:** `src/igscraper/services/replies_expander.py:244`

```python
def _execute_js(self, script: str) -> dict:
    """Runs JS inside the current page."""
    return self.driver.execute_script(f"return (async ()=>{{ {script} }})()")
```

The `ReplyExpander` injects complex async JavaScript for:
- Clicking reply buttons
- Waiting for DOM changes
- Scrolling and searching
- Human-like delays

**Example JavaScript from ReplyExpander:**
```javascript
async function clickAllReplyButtons(options = {}) {
    const container = document.querySelector(containerSelector);
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    
    async function clickWithDelay(el) {
        await randomPause(250 + Math.random() * 400);
        el.click();
        await randomPause(200 + Math.random() * 300);
    }
    
    // ... complex logic for finding and clicking buttons ...
    
    return {
        clickedCount,
        clickedTexts,
        logs,
        timestamp: new Date().toISOString(),
    };
}
```

### JavaScript Utilities

#### Performance API Usage

**`performance.getEntriesByType("resource")`**
Used to extract network resource information:

```python
js = """
const resources = (performance.getEntriesByType ? 
    performance.getEntriesByType("resource") : [])
    .filter(e => e && e.name && 
        e.name.startsWith('http://') || e.name.startsWith('https://') &&
        e.name.toLowerCase().includes(".mp4"));
return resources.map(e => ({
    url: e.name,
    transferSize: e.transferSize || 0,
    duration: e.duration || 0,
    // ...
}));
"""
```

#### DOM Manipulation

**Element Clicking via JavaScript:**
```python
driver.execute_script(
    """
    (function(cx, cy){
        const targ = document.elementFromPoint(cx, cy) || document.body;
        ['mouseover','mousemove','mousedown','mouseup','click'].forEach(name => {
            const ev = new MouseEvent(name, {
                bubbles:true, 
                cancelable:true, 
                clientX:cx, 
                clientY:cy
            });
            targ.dispatchEvent(ev);
        });
    })(arguments[0], arguments[1]);
    """,
    int(rect["cx"]),
    int(rect["cy"]),
)
```

---

## Security and Monitoring

### Driver Patching (`chrome.py`)

**Location:** `src/igscraper/chrome.py:56`

The codebase implements security monitoring by patching WebDriver methods to detect suspicious navigation:

```python
def patch_driver(driver):
    # Patch WebDriver.get
    original_get = driver.get
    def safe_get(url, *args, **kwargs):
        result = original_get(url, *args, **kwargs)
        _check_page(driver.current_url)  # Validate URL
        return result
    driver.get = safe_get
    
    # Patch WebElement.click
    original_click = webdriver.remote.webelement.WebElement.click
    def safe_click(self, *args, **kwargs):
        result = original_click(self, *args, **kwargs)
        _check_page(self.parent.current_url)
        return result
    webdriver.remote.webelement.WebElement.click = safe_click
    
    # Patch execute_script
    original_exec = driver.execute_script
    def safe_exec(script, *args, **kwargs):
        result = original_exec(script, *args, **kwargs)
        _check_page(driver.current_url)
        return result
    driver.execute_script = safe_exec
    
    # Background watchdog thread
    def watchdog():
        while True:
            try:
                _check_page(driver.current_url)
                time.sleep(1)
            except Exception:
                break
    threading.Thread(target=watchdog, daemon=True).start()
    
    return driver
```

**URL Validation:**
```python
def is_allowed_instagram_url(url: str) -> bool:
    if url in ("about:blank", "data:,"):
        return True
    
    parsed = urlparse(url)
    if parsed.netloc != "www.instagram.com":
        return False
    
    path_parts = [p for p in parsed.path.strip("/").split("/") if p]
    
    # Allow: /, /p/{id}/, /reel/{id}/, /{username}/, /{username}/p/{id}/
    # ... validation logic ...
    
    return True

def _check_page(url):
    if not is_allowed_instagram_url(url):
        print(f"⚠️ Suspicious navigation: {url}")
        input("Press Enter to continue after checking...")
```

This security mechanism:
- Monitors all navigation events
- Validates URLs against allowed Instagram patterns
- Alerts on suspicious navigation
- Runs a background watchdog thread for continuous monitoring

---

## Page Object Model Implementation

### BasePage Class

**Location:** `src/igscraper/pages/base_page.py`

Provides common WebDriver operations:

```python
class BasePage:
    def __init__(self, driver: WebDriver):
        self.driver = driver
        self.wait = WebDriverWait(driver, 10)
    
    def find(self, locator: tuple) -> WebElement:
        return self.wait.until(EC.presence_of_element_located(locator))
    
    def find_all(self, locator: tuple) -> list[WebElement]:
        return self.wait.until(EC.presence_of_all_elements_located(locator))
    
    def click(self, element: WebElement) -> None:
        self.driver.execute_script("arguments[0].click();", element)
    
    def scroll_into_view(self, element: WebElement) -> None:
        self.driver.execute_script("arguments[0].scrollIntoView();", element)
```

### ProfilePage Class

**Location:** `src/igscraper/pages/profile_page.py`

Extends `BasePage` for Instagram profile-specific interactions:

```python
class ProfilePage(BasePage):
    def __init__(self, driver, config):
        super().__init__(driver)
        self.config = config
        self.scroller = HumanScroller(self.driver)
    
    def navigate_to_profile(self, handle: str) -> None:
        url = f"https://www.instagram.com/{handle}/"
        self.driver.get(url)
        self.wait_for_sections()
    
    def get_visible_post_elements(self) -> List[WebElement]:
        xpath_for_class = "//*[@class and contains(concat(' ', @class, ' '), ' _ac7v ')]"
        elements_with_class_xpath = self.driver.find_elements(By.XPATH, xpath_for_class)
        all_href_elem = [row.find_elements(By.CSS_SELECTOR, "a") for row in elements_with_class_xpath]
        return [elem for sublist in all_href_elem for elem in sublist]
    
    def scroll_and_collect_(self, limit: int) -> List[str]:
        posts = []
        last_height = self.driver.execute_script("return document.body.scrollHeight")
        while len(posts) < limit:
            new_posts = self.get_visible_post_elements()
            for post in new_posts:
                href = post.get_attribute("href")
                if href and href not in posts:
                    posts.append(href)
            self.scroller.perform(4)  # Human-like scrolling
            new_height = self.driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height
        return posts
```

---

## Performance Logging

### Configuration

Performance logging is enabled during WebDriver initialization:

```python
options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
perf_log_prefs = {"enableNetwork": True}
options.set_capability("goog:perfLoggingPrefs", perf_log_prefs)
```

### Log Retrieval

Performance logs are retrieved using:

```python
logs = driver.get_log("performance")
```

Each log entry contains:
- `level`: Log level (e.g., "INFO")
- `message`: JSON string containing CDP event data
- `timestamp`: Event timestamp

### Log Entry Structure

```python
entry = {
    "level": "INFO",
    "message": '{"message":{"method":"Network.responseReceived","params":{...}}}',
    "timestamp": 1234567890
}

# Parse message
msg = json.loads(entry["message"])["message"]
method = msg.get("method")  # e.g., "Network.responseReceived"
params = msg.get("params")   # Contains request/response details
```

### Common CDP Events Captured

1. **`Network.requestWillBeSent`**: Request about to be sent
   - `params.request.url`: Request URL
   - `params.requestId`: Unique request identifier
   - `params.request.method`: HTTP method
   - `params.request.headers`: Request headers

2. **`Network.responseReceived`**: Response received
   - `params.response.url`: Response URL
   - `params.response.status`: HTTP status code
   - `params.response.headers`: Response headers
   - `params.response.mimeType`: Content type
   - `params.requestId`: Matches request ID

---

## Common Patterns and Utilities

### WebDriverWait Usage

**Explicit Waits:**
```python
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

wait = WebDriverWait(driver, 10)
element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "selector")))
```

**Common Expected Conditions:**
- `EC.presence_of_element_located()`: Element exists in DOM
- `EC.visibility_of_element_located()`: Element is visible
- `EC.element_to_be_clickable()`: Element is clickable
- `EC.presence_of_all_elements_located()`: All matching elements exist

### ActionChains Usage

**Human-like Interactions:**
```python
from selenium.webdriver import ActionChains

actions = ActionChains(driver)
actions.move_to_element(element).pause(0.02).click().perform()
```

**Common Patterns:**
- Mouse movement simulation
- Click with delays
- Scroll actions
- Keyboard input

### Element Finding Strategies

**By CSS Selector:**
```python
element = driver.find_element(By.CSS_SELECTOR, "main a[href^='/p/']")
elements = driver.find_elements(By.CSS_SELECTOR, "div.html-div")
```

**By XPath:**
```python
xpath = "//*[@class and contains(concat(' ', @class, ' '), ' _ac7v ')]"
elements = driver.find_elements(By.XPATH, xpath)
```

**By Tag Name:**
```python
sections = driver.find_elements(By.TAG_NAME, "section")
```

### Tab/Window Management

**Get Current Window Handle:**
```python
main_handle = driver.current_window_handle
```

**Get All Window Handles:**
```python
all_handles = driver.window_handles
```

**Switch to Window:**
```python
driver.switch_to.window(window_handle)
```

**Close Current Window:**
```python
driver.close()
```

**Switch Back to Main Window:**
```python
if main_handle in driver.window_handles:
    driver.switch_to.window(main_handle)
elif driver.window_handles:
    driver.switch_to.window(driver.window_handles[0])
```

### Cookie Management

**Add Cookies:**
```python
for cookie in cookies:
    if 'expiry' in cookie and isinstance(cookie['expiry'], float):
        cookie['expiry'] = int(cookie['expiry'])
    driver.add_cookie(cookie)
```

**Get Cookies:**
```python
cookies = driver.get_cookies()
```

**Save Cookies:**
```python
import pickle
pickle.dump(driver.get_cookies(), open("cookies.pkl", "wb"))
```

### Error Handling Patterns

**Try-Except with Logging:**
```python
try:
    element = driver.find_element(By.CSS_SELECTOR, "selector")
    element.click()
except NoSuchElementException:
    logger.warning("Element not found")
except TimeoutException:
    logger.error("Timeout waiting for element")
except WebDriverException as e:
    logger.exception(f"WebDriver error: {e}")
```

**Stale Element Handling:**
```python
try:
    href = post.get_attribute("href")
except StaleElementReferenceException:
    logger.debug("Skipped stale element")
    continue
```

### Human-like Behavior Simulation

**Random Delays:**
```python
import random
import time

time.sleep(random.uniform(1.5, 3.0))
```

**Mouse Movement:**
```python
def human_mouse_move(driver, duration=0.5):
    # Simulate human-like mouse movement
    actions = ActionChains(driver)
    # ... movement logic ...
    actions.perform()
```

**Scroll Simulation:**
```python
class HumanScroller:
    def perform(self, steps=4):
        for _ in range(steps):
            delta = random.uniform(100, 300)
            driver.execute_script(f"window.scrollBy(0, {delta});")
            time.sleep(random.uniform(0.3, 0.7))
```

---

## Summary

The Instagram Profile Scraper uses Selenium extensively for:

1. **Browser Automation**: Full WebDriver lifecycle management
2. **Network Monitoring**: Performance log capture and CDP integration
3. **Data Extraction**: JavaScript execution for DOM manipulation
4. **Security**: URL validation and navigation monitoring
5. **Human-like Behavior**: Delays, mouse movements, scrolling
6. **Tab Management**: Multi-tab scraping for batch processing
7. **Authentication**: Cookie-based login
8. **Error Handling**: Robust exception handling with retries

The codebase demonstrates advanced Selenium patterns including:
- Chrome DevTools Protocol integration
- Performance log analysis
- Complex JavaScript injection
- Security monitoring
- Page Object Model architecture
- Human-like interaction simulation

