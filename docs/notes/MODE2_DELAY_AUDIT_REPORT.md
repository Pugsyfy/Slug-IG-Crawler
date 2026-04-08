# Mode 2 Extract Comments — Delay Audit + Configuration Plan

## Executive Summary

This report documents all delays in the Mode 2 "extract comments" execution flow, classifies them as config-driven or hardcoded, and provides a plan to standardize delay settings using 4 tiers based on `max_comments`.

---

## 1. Delay Breakdown (What + Where)

### 1.1 Pre-Comment Extraction Delays

#### Delay 1.1.1: Post Tab Page Load Wait
- **Location**: `selenium_backend.py:936` in `_scrape_and_close_tab()`
- **Delay**: `random_delay(2.4, 4.0)` seconds
- **Purpose**: Wait for page to load after tab switch/refresh
- **Type**: **HARDCODED**
- **Context**: Applied before comment extraction begins

#### Delay 1.1.2: Human Mouse Move (Conditional)
- **Location**: `selenium_backend.py:939-944` in `_scrape_and_close_tab()`
- **Delay**: `self.config.main.human_mouse_move_duration` (default: 0.5s)
- **Purpose**: Anti-bot measure (random 2/7 chance)
- **Type**: **CONFIG-DRIVEN** (via `human_mouse_move_duration`)
- **Context**: Only executed if random condition is met

---

### 1.2 Comment Container Discovery Delays

#### Delay 1.2.1: WebDriverWait for Comments Container
- **Location**: `selenium_backend.py:1521` in `_extract_comments_from_captured_requests()`
- **Delay**: Up to 10 seconds (timeout)
- **Purpose**: Wait for comments container to appear in DOM
- **Type**: **HARDCODED**
- **Context**: Initial wait before container discovery

#### Delay 1.2.2: Container Retry Wait
- **Location**: `selenium_backend.py:1508, 1514` in `get_valid_container()`
- **Delay**: `time.sleep(1)` second per retry (max 3 retries)
- **Purpose**: Wait between container discovery retry attempts
- **Type**: **HARDCODED**
- **Context**: Retry logic for container validation

---

### 1.3 ReplyExpander Initialization Delays

#### Delay 1.3.1: ReplyExpander Base Pause (JS-side)
- **Location**: `selenium_backend.py:1534` → `ReplyExpander.__init__()` → JS execution
- **Delay**: `base_pause_ms=600` (0.6 seconds) — used as base for all JS-side pauses
- **Purpose**: Base pause duration for human-like interaction timing in JavaScript
- **Type**: **HARDCODED** (passed as parameter, but value is fixed)
- **Context**: Used in `expand_replies()` JS code for:
  - Scroll search pauses: `basePauseMs * rand(0.8, 1.3)` = ~480-780ms
  - Scan pauses (25% chance): `basePauseMs * rand(1.5, 3.0)` = ~900-1800ms
  - Click pre-pause: `200 + Math.random() * 400` = 200-600ms
  - Click post-pause: `200 + Math.random() * 300` = 200-500ms
  - Long pause chance (25%): `basePauseMs * rand(2, 4)` = ~1200-2400ms
  - Reading pause (30% chance): `basePauseMs * rand(1.5, 3.5)` = ~900-2100ms
  - Settle wait: `settleWaitMs=1000` (1 second)

#### Delay 1.3.2: ReplyExpander Settle Wait
- **Location**: `replies_expander.py:26` → JS execution
- **Delay**: `settle_wait_ms=1000` (1 second, default)
- **Purpose**: Final wait after all clicks complete
- **Type**: **HARDCODED** (default value, not configurable)
- **Context**: Applied at end of `expand_replies()` execution

---

### 1.4 Batch Processing Delays

#### Delay 1.4.1: Between-Batch Pause
- **Location**: `selenium_backend.py:1714` in `_extract_comments_from_captured_requests()`
- **Delay**: `time.sleep(random.uniform(1.5, 3.0))` seconds
- **Purpose**: Realism and stability between comment extraction batches
- **Type**: **HARDCODED**
- **Context**: Applied after each batch completes, before next batch

#### Delay 1.4.2: Fire Human Scroll Signals Delay
- **Location**: `selenium_backend.py:1476` in `fire_human_scroll_signals()`
- **Delay**: `time.sleep(random.uniform(0.4, 0.8))` seconds
- **Purpose**: Allow Instagram to emit GraphQL after scroll signals
- **Type**: **HARDCODED**
- **Context**: Currently commented out in main flow, but present in utility

---

### 1.5 ReplyExpander.expand_replies() JS-Side Delays

All delays below occur inside JavaScript executed by `ReplyExpander.expand_replies()`:

#### Delay 1.5.1: Gentle Search Scroll Pause
- **Location**: `replies_expander.py:148` (JS code)
- **Delay**: `basePauseMs * rand(0.8, 1.3)` = ~480-780ms (using base_pause_ms=600)
- **Purpose**: Pause between scroll steps while searching for reply buttons
- **Type**: **HARDCODED** (derived from hardcoded `base_pause_ms=600`)
- **Context**: Per scroll step in `gentleSearchScroll()`

#### Delay 1.5.2: Scan Pause (Occasional)
- **Location**: `replies_expander.py:150-153` (JS code)
- **Delay**: `basePauseMs * rand(1.5, 3.0)` = ~900-1800ms (25% chance)
- **Purpose**: Human-like scanning pause while searching
- **Type**: **HARDCODED** (derived from hardcoded `base_pause_ms=600`)
- **Context**: Random chance during search scroll

#### Delay 1.5.3: Click Pre-Pause
- **Location**: `replies_expander.py:161` (JS code)
- **Delay**: `200 + Math.random() * 400` = 200-600ms
- **Purpose**: Pause before clicking reply button
- **Type**: **HARDCODED**
- **Context**: Before each button click

#### Delay 1.5.4: Click Post-Pause
- **Location**: `replies_expander.py:167` (JS code)
- **Delay**: `200 + Math.random() * 300` = 200-500ms
- **Purpose**: Pause after clicking reply button
- **Type**: **HARDCODED**
- **Context**: After each button click

#### Delay 1.5.5: Scroll Into View Pause
- **Location**: `replies_expander.py:186` (JS code)
- **Delay**: `basePauseMs * rand(0.7, 1.3)` = ~420-780ms
- **Purpose**: Pause after scrolling element into view
- **Type**: **HARDCODED** (derived from hardcoded `base_pause_ms=600`)
- **Context**: Before clicking element

#### Delay 1.5.6: Long Pause (Occasional)
- **Location**: `replies_expander.py:188-189` (JS code)
- **Delay**: `basePauseMs * rand(2, 4)` = ~1200-2400ms (25% chance via `longPauseChance`)
- **Purpose**: Human-like longer reading pause
- **Type**: **HARDCODED** (derived from hardcoded `base_pause_ms=600`)
- **Context**: Random chance before clicking

#### Delay 1.5.7: Reading Pause After Expand (Occasional)
- **Location**: `replies_expander.py:197-200` (JS code)
- **Delay**: `basePauseMs * rand(1.5, 3.5)` = ~900-2100ms (30% chance)
- **Purpose**: Human-like reading pause after expanding replies
- **Type**: **HARDCODED** (derived from hardcoded `base_pause_ms=600`)
- **Context**: Random chance after each click

---

### 1.6 ReplyExpander.only_scroll() Delays (Scroll-Only Mode)

#### Delay 1.6.1: Initial Focus Wait
- **Location**: `replies_expander.py:1462` in `only_scroll()`
- **Delay**: `time.sleep(random.uniform(0.3, 0.6))` seconds
- **Purpose**: Wait after initial container focus
- **Type**: **HARDCODED**
- **Context**: Before scroll loop begins

#### Delay 1.6.2: Key Press Burst Delay
- **Location**: `replies_expander.py:1491` in `only_scroll()`
- **Delay**: `time.sleep(random.uniform(0.15, 0.35))` seconds per key press
- **Purpose**: Delay between key presses in burst (1-3 keys)
- **Type**: **HARDCODED**
- **Context**: Per key in burst loop

#### Delay 1.6.3: Upward Correction Delay
- **Location**: `replies_expander.py:1497` in `only_scroll()`
- **Delay**: `time.sleep(random.uniform(0.08, 0.18))` seconds (15% chance)
- **Purpose**: Delay after upward correction key press
- **Type**: **HARDCODED**
- **Context**: Random chance for upward correction

#### Delay 1.6.4: Reading Pause (Occasional)
- **Location**: `replies_expander.py:1502` in `only_scroll()`
- **Delay**: `time.sleep(random.uniform(0.8, 2.0))` seconds (25% chance)
- **Purpose**: Human-like reading pause during scrolling
- **Type**: **HARDCODED**
- **Context**: Random chance per scroll step

#### Delay 1.6.5: Periodic Refocus Delay
- **Location**: `replies_expander.py:1508` in `only_scroll()`
- **Delay**: `time.sleep(random.uniform(0.2, 0.4))` seconds (every 2 steps)
- **Purpose**: Delay after refocusing container
- **Type**: **HARDCODED**
- **Context**: Every 2nd scroll step

#### Delay 1.6.6: Page Scroll Clamp Delay
- **Location**: `replies_expander.py:1518` in `only_scroll()`
- **Delay**: `time.sleep(random.uniform(0.05, 0.15))` seconds (if clamp occurs)
- **Purpose**: Delay after clamping page scroll
- **Type**: **HARDCODED**
- **Context**: Only if page scroll was clamped

---

### 1.7 Rate Limit & Error Handling Delays

#### Delay 1.7.1: Rate Limit Cooldown (Exponential Backoff)
- **Location**: `selenium_backend.py:1646-1648` in `_extract_comments_from_captured_requests()`
- **Delay**: `random.uniform(240, 360) * min(2 ** (attempts - 1), 16)` seconds
  - Attempt 1: 240-360 seconds (4-6 minutes)
  - Attempt 2: 480-720 seconds (8-12 minutes)
  - Attempt 3: 960-1440 seconds (16-24 minutes)
  - Attempt 4+: 3840-5760 seconds (64-96 minutes, capped at 16x multiplier)
- **Purpose**: Exponential backoff when rate limit is detected
- **Type**: **HARDCODED** (base_min=240, base_max=360, max_multiplier=16)
- **Context**: Triggered when `_handle_comment_load_error()` returns True

#### Delay 1.7.2: Comment Load Error Retry Wait
- **Location**: `selenium_backend.py:1771` in `_handle_comment_load_error()`
- **Delay**: `time.sleep(random.uniform(4.5, 8.0))` seconds
- **Purpose**: Wait before retrying after detecting "Comments can't be loaded" error
- **Type**: **HARDCODED**
- **Context**: After detecting error, before page refresh

---

### 1.8 Post-Level Batch Delays (Outside Comment Extraction)

#### Delay 1.8.1: Batch Start Delay
- **Location**: `selenium_backend.py:1132` in `scrape_posts_in_batches()`
- **Delay**: `time.sleep(random.uniform(1, 5))` seconds
- **Purpose**: Delay before starting each batch of posts
- **Type**: **HARDCODED**
- **Context**: Before opening batch of tabs

#### Delay 1.8.2: Post Tab Open Delay
- **Location**: `selenium_backend.py:1138` in `scrape_posts_in_batches()`
- **Delay**: `time.sleep(random.uniform(1, 5))` seconds
- **Purpose**: Delay between opening each post tab
- **Type**: **HARDCODED**
- **Context**: Between tab opens within batch

#### Delay 1.8.3: Tab Load Wait
- **Location**: `selenium_backend.py:1156` in `scrape_posts_in_batches()`
- **Delay**: `time.sleep(random.uniform(0.8, 1.5))` seconds
- **Purpose**: Wait for new tab to start loading
- **Type**: **HARDCODED**
- **Context**: After opening each tab

#### Delay 1.8.4: Between-Post Scrape Delay
- **Location**: `selenium_backend.py:1176` in `scrape_posts_in_batches()`
- **Delay**: `time.sleep(random.uniform(3, 10))` seconds
- **Purpose**: Delay between scraping posts in batch
- **Type**: **HARDCODED**
- **Context**: Before scraping each post

#### Delay 1.8.5: Between-Batch Rate Limit Delay
- **Location**: `selenium_backend.py:1246` in `scrape_posts_in_batches()`
- **Delay**: `random_delay(self.config.main.rate_limit_seconds_min, self.config.main.rate_limit_seconds_max)`
  - Default: 2-5 seconds (configurable)
- **Purpose**: Rate limiting between batches of posts
- **Type**: **CONFIG-DRIVEN** (via `rate_limit_seconds_min` and `rate_limit_seconds_max`)
- **Context**: After completing each batch

#### Delay 1.8.6: Tab Open Retry Wait
- **Location**: `selenium_backend.py:1336` in `open_href_in_new_tab()`
- **Delay**: `time.sleep(0.5 + random.random() * 0.5)` = 0.5-1.0 seconds
- **Purpose**: Wait between checks for new tab handle
- **Type**: **HARDCODED**
- **Context**: Retry loop for tab detection

---

### 1.9 Other Utility Delays

#### Delay 1.9.1: Post Title Extraction Wait
- **Location**: `selenium_backend.py:1356` in `get_post_title_data()`
- **Delay**: `random_delay(0.4, 2.3)` seconds
- **Purpose**: Wait to ensure content is fully loaded
- **Type**: **HARDCODED**
- **Context**: Before executing JS to extract title (not in comment extraction path if `scrape_using_captured_requests=True`)

---

## 2. Config-Driven vs Hardcoded Classification

### Summary Statistics
- **Total Delays Identified**: 28
- **Config-Driven**: 3
- **Hardcoded**: 25

### Config-Driven Delays (3)

1. **`human_mouse_move_duration`** (Delay 1.1.2)
   - Config key: `main.human_mouse_move_duration`
   - Default: 0.5 seconds
   - Location: `selenium_backend.py:940`

2. **`rate_limit_seconds_min` / `rate_limit_seconds_max`** (Delay 1.8.5)
   - Config keys: `main.rate_limit_seconds_min`, `main.rate_limit_seconds_max`
   - Defaults: 2-5 seconds
   - Location: `selenium_backend.py:1246`

3. **`comment_no_new_retries`** (indirectly affects termination, not a delay)
   - Config key: `main.comment_no_new_retries`
   - Default: 3
   - Location: `selenium_backend.py:1551, 1629`

### Hardcoded Delays (25)

All other delays listed in Section 1 are hardcoded with fixed values or fixed ranges.

**Critical Hardcoded Delays:**
- Post page load wait: 2.4-4.0s
- Container discovery retries: 1s per retry
- ReplyExpander `base_pause_ms`: 600ms (affects all JS-side timing)
- Between-batch pause: 1.5-3.0s
- Rate limit cooldown: 240-360s base (exponential backoff)
- Comment load error wait: 4.5-8.0s
- All `only_scroll()` delays: various hardcoded ranges
- All post-level batch delays: various hardcoded ranges

---

## 3. Plan to Standardize Delay Settings

### 3.1 Configuration Structure

Create a new configuration section `[main.comment_extraction_delays]` with 4 tiers based on `max_comments`:

```toml
[main.comment_extraction_delays]
# Tier selection is automatic based on max_comments:
# Tier 1: max_comments < 200
# Tier 2: 200 <= max_comments < 700
# Tier 3: 700 <= max_comments < 2000
# Tier 4: 2000 <= max_comments < 4000

[tier_1]  # max_comments < 200
post_page_load_min = 1.5
post_page_load_max = 2.5
container_wait_timeout = 8
container_retry_delay = 0.8
reply_expander_base_pause_ms = 400
reply_expander_settle_wait_ms = 800
between_batch_pause_min = 1.0
between_batch_pause_max = 2.0
only_scroll_initial_focus_min = 0.2
only_scroll_initial_focus_max = 0.4
only_scroll_key_press_min = 0.1
only_scroll_key_press_max = 0.25
only_scroll_reading_pause_min = 0.6
only_scroll_reading_pause_max = 1.5
rate_limit_cooldown_base_min = 180  # 3 minutes
rate_limit_cooldown_base_max = 240  # 4 minutes
rate_limit_cooldown_max_multiplier = 8
comment_load_error_wait_min = 3.0
comment_load_error_wait_max = 5.0

[tier_2]  # 200 <= max_comments < 700
post_page_load_min = 2.4
post_page_load_max = 4.0
container_wait_timeout = 10
container_retry_delay = 1.0
reply_expander_base_pause_ms = 600
reply_expander_settle_wait_ms = 1000
between_batch_pause_min = 1.5
between_batch_pause_max = 3.0
only_scroll_initial_focus_min = 0.3
only_scroll_initial_focus_max = 0.6
only_scroll_key_press_min = 0.15
only_scroll_key_press_max = 0.35
only_scroll_reading_pause_min = 0.8
only_scroll_reading_pause_max = 2.0
rate_limit_cooldown_base_min = 240  # 4 minutes
rate_limit_cooldown_base_max = 360  # 6 minutes
rate_limit_cooldown_max_multiplier = 16
comment_load_error_wait_min = 4.5
comment_load_error_wait_max = 8.0

[tier_3]  # 700 <= max_comments < 2000
post_page_load_min = 3.0
post_page_load_max = 5.0
container_wait_timeout = 12
container_retry_delay = 1.2
reply_expander_base_pause_ms = 800
reply_expander_settle_wait_ms = 1200
between_batch_pause_min = 2.0
between_batch_pause_max = 4.0
only_scroll_initial_focus_min = 0.4
only_scroll_initial_focus_max = 0.7
only_scroll_key_press_min = 0.2
only_scroll_key_press_max = 0.4
only_scroll_reading_pause_min = 1.0
only_scroll_reading_pause_max = 2.5
rate_limit_cooldown_base_min = 300  # 5 minutes
rate_limit_cooldown_base_max = 420  # 7 minutes
rate_limit_cooldown_max_multiplier = 16
comment_load_error_wait_min = 5.0
comment_load_error_wait_max = 10.0

[tier_4]  # 2000 <= max_comments < 4000
post_page_load_min = 4.0
post_page_load_max = 6.0
container_wait_timeout = 15
container_retry_delay = 1.5
reply_expander_base_pause_ms = 1000
reply_expander_settle_wait_ms = 1500
between_batch_pause_min = 2.5
between_batch_pause_max = 5.0
only_scroll_initial_focus_min = 0.5
only_scroll_initial_focus_max = 0.8
only_scroll_key_press_min = 0.25
only_scroll_key_press_max = 0.45
only_scroll_reading_pause_min = 1.2
only_scroll_reading_pause_max = 3.0
rate_limit_cooldown_base_min = 360  # 6 minutes
rate_limit_cooldown_base_max = 480  # 8 minutes
rate_limit_cooldown_max_multiplier = 16
comment_load_error_wait_min = 6.0
comment_load_error_wait_max = 12.0
```

### 3.2 Implementation Plan

#### Step 1: Add Configuration Model
- **File**: `src/igscraper/config.py`
- **Action**: Add `CommentExtractionDelaysConfig` class with 4 tier subclasses
- **Details**:
  ```python
  class CommentExtractionDelaysTier(BaseModel):
      post_page_load_min: float
      post_page_load_max: float
      container_wait_timeout: int
      container_retry_delay: float
      reply_expander_base_pause_ms: int
      reply_expander_settle_wait_ms: int
      between_batch_pause_min: float
      between_batch_pause_max: float
      only_scroll_initial_focus_min: float
      only_scroll_initial_focus_max: float
      only_scroll_key_press_min: float
      only_scroll_key_press_max: float
      only_scroll_reading_pause_min: float
      only_scroll_reading_pause_max: float
      rate_limit_cooldown_base_min: float
      rate_limit_cooldown_base_max: float
      rate_limit_cooldown_max_multiplier: int
      comment_load_error_wait_min: float
      comment_load_error_wait_max: float

  class CommentExtractionDelaysConfig(BaseModel):
      tier_1: CommentExtractionDelaysTier
      tier_2: CommentExtractionDelaysTier
      tier_3: CommentExtractionDelaysTier
      tier_4: CommentExtractionDelaysTier
      
      def get_tier(self, max_comments: int) -> CommentExtractionDelaysTier:
          if max_comments < 200:
              return self.tier_1
          elif max_comments < 700:
              return self.tier_2
          elif max_comments < 2000:
              return self.tier_3
          else:
              return self.tier_4
  ```

#### Step 2: Add Helper Method to SeleniumBackend
- **File**: `src/igscraper/backends/selenium_backend.py`
- **Action**: Add method to get current tier delays
- **Details**:
  ```python
  def _get_comment_delays(self) -> CommentExtractionDelaysTier:
      """Get delay tier based on current max_comments setting."""
      max_comments = self.config.main.max_comments
      return self.config.main.comment_extraction_delays.get_tier(max_comments)
  ```

#### Step 3: Replace Hardcoded Delays in `_scrape_and_close_tab()`
- **File**: `src/igscraper/backends/selenium_backend.py`
- **Location**: Line 936
- **Change**: Replace `random_delay(2.4, 4.0)` with tier-based delays
- **Code**:
  ```python
  delays = self._get_comment_delays()
  random_delay(delays.post_page_load_min, delays.post_page_load_max)
  ```

#### Step 4: Replace Hardcoded Delays in `_extract_comments_from_captured_requests()`
- **File**: `src/igscraper/backends/selenium_backend.py`
- **Locations**:
  - Line 1508, 1514: Container retry delay
  - Line 1521: Container wait timeout
  - Line 1534: ReplyExpander base_pause_ms
  - Line 1646-1648: Rate limit cooldown
  - Line 1714: Between-batch pause
  - Line 1771: Comment load error wait
- **Changes**: Replace all hardcoded values with tier-based delays

#### Step 5: Update ReplyExpander to Accept Configurable Delays
- **File**: `src/igscraper/services/replies_expander.py`
- **Action**: Modify `__init__()` and `with_container()` to accept delay parameters
- **Changes**:
  - Accept `base_pause_ms` and `settle_wait_ms` as parameters (already supported)
  - Pass these from `_extract_comments_from_captured_requests()` using tier delays

#### Step 6: Update `only_scroll()` to Accept Configurable Delays
- **File**: `src/igscraper/services/replies_expander.py`
- **Action**: Add delay parameters to `only_scroll()` method signature
- **Changes**:
  - Add parameters: `initial_focus_min`, `initial_focus_max`, `key_press_min`, `key_press_max`, `reading_pause_min`, `reading_pause_max`
  - Replace hardcoded values in lines 1462, 1491, 1502 with parameters
  - Pass these from `_extract_comments_from_captured_requests()` using tier delays

#### Step 7: Update Post-Level Batch Delays (Optional)
- **File**: `src/igscraper/backends/selenium_backend.py`
- **Action**: Consider making post-level delays configurable (currently outside comment extraction scope)
- **Note**: These delays are in `scrape_posts_in_batches()` and affect overall scraping, not just comment extraction. Can be left as-is or made configurable separately.

### 3.3 Migration Strategy

1. **Phase 1**: Add configuration structure with default values matching current hardcoded values
2. **Phase 2**: Implement tier selection logic
3. **Phase 3**: Replace delays one module at a time (test after each)
4. **Phase 4**: Remove all hardcoded delay values
5. **Phase 5**: Add validation to ensure tier values are reasonable

### 3.4 Testing Plan

1. **Unit Tests**: Test tier selection logic for all 4 tiers
2. **Integration Tests**: Verify delays are applied correctly in comment extraction flow
3. **Performance Tests**: Measure total extraction time for each tier with various `max_comments` values
4. **Regression Tests**: Ensure existing functionality is not broken

### 3.5 Backward Compatibility

- Default tier values should match current hardcoded values (Tier 2 matches current defaults)
- If `comment_extraction_delays` section is missing from config, fall back to Tier 2 defaults
- Log warning when using fallback defaults

---

## 4. Delay Value Rationale by Tier

### Tier 1 (max_comments < 200): Fast & Light
- **Rationale**: Small comment sets, can be more aggressive
- **Focus**: Minimize overhead, faster completion
- **Trade-off**: Slightly higher risk of rate limiting (acceptable for small sets)

### Tier 2 (200 <= max_comments < 700): Balanced
- **Rationale**: Medium comment sets, current default behavior
- **Focus**: Balance between speed and safety
- **Trade-off**: Standard rate limiting protection

### Tier 3 (700 <= max_comments < 2000): Conservative
- **Rationale**: Large comment sets, need more caution
- **Focus**: Emphasize stability and rate limit avoidance
- **Trade-off**: Slower but more reliable

### Tier 4 (2000 <= max_comments < 4000): Very Conservative
- **Rationale**: Very large comment sets, maximum caution required
- **Focus**: Maximum stability, minimize rate limit risk
- **Trade-off**: Slowest but safest for large extractions

---

## 5. Additional Considerations

### 5.1 JS-Side Delays in ReplyExpander
- JS-side delays (in `expand_replies()`) are calculated from `base_pause_ms`
- These will automatically scale with tier selection since `base_pause_ms` is tier-based
- No additional changes needed for JS-side delays

### 5.2 Rate Limit Cooldown Exponential Backoff
- Base cooldown values are tier-based
- Multiplier logic remains the same (exponential with cap)
- Higher tiers have longer base cooldowns to be more conservative

### 5.3 Post-Level Delays
- Post-level batch delays (Section 1.8) are outside comment extraction scope
- These can remain as-is or be made configurable separately
- Recommendation: Keep separate from comment extraction delays for clarity

### 5.4 Dynamic Tier Selection
- Tier is selected at the start of `_extract_comments_from_captured_requests()` based on `config.main.max_comments`
- If `max_comments` changes during execution (per-post override), tier should be re-evaluated
- Current per-post override mechanism (lines 1187-1216) already handles this correctly

---

## 6. Summary

### Current State
- **25 hardcoded delays** across the comment extraction flow
- **3 config-driven delays** (only 2 are actual delays)
- No tier-based scaling based on `max_comments`

### Proposed State
- **All delays configurable** via tier-based system
- **4 tiers** automatically selected based on `max_comments`
- **Consistent delay structure** across all delay points
- **Backward compatible** with fallback to Tier 2 defaults

### Implementation Effort
- **Estimated changes**: ~15-20 code locations
- **Configuration additions**: 1 new config section with 4 tier subsections
- **Testing required**: Unit tests, integration tests, performance validation

---

**Report Generated**: 2025-01-XX  
**Codebase Version**: ig_profile_scraper (Mode 2 extract comments flow)  
**Status**: Plan Only — No Code Changes Made
