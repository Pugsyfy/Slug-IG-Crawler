# POST Mode Path Construction Analysis

## Executive Summary

**CRITICAL FINDING**: Multiple POST jobs with the same `run_name_for_url_file` will write to the **same directory** but create **distinct files per post** (due to shortcode in filename). However, there are potential issues with:
1. **Shared directory structure** - all jobs with same run_name use same base directory
2. **Datetime computed once per pipeline** - not per post, not per job
3. **No job_id or run_id in paths** - multiple jobs can collide on directory level

## Detailed Analysis

### 1. Path Construction Flow

#### Step 1: Initial Path Expansion (Once Per Pipeline Run)
**Location**: `src/igscraper/pipeline.py`, `_scrape_from_url_file()`, lines 180-195

```python
# Line 180: datetime computed ONCE per pipeline run
datetime_now = datetime.datetime.now().strftime("%Y%m%d_%H%M")

# Line 190: target_profile set to run_name
run_config.main.target_profile = run_name  # e.g., "job_abc123"

# Line 191-194: substitutions computed ONCE
substitutions = {
    "date": datetime_now.split('_')[0],      # e.g., "20260108"
    "datetime": datetime_now,                 # e.g., "20260108_1430"
}

# Line 195: expand_paths called ONCE per pipeline run
expand_paths(run_config, substitutions)
```

**Result**: Paths expanded like:
- `post_entity_path = "outputs/20260108/job_abc123/post_entity_job_abc123_20260108_1430.jsonl"`
- `metadata_path = "outputs/20260108/job_abc123/metadata_job_abc123.jsonl"`

#### Step 2: Per-Post Path Updates
**Location**: `src/igscraper/backends/selenium_backend.py`, line 927

```python
# Called for EACH post being scraped
self.config.data.post_entity_path = update_post_entity_path(
    self.config.data.post_entity_path, 
    post_shortcode
)
```

**Location**: `src/igscraper/utils.py`, `update_post_entity_path()`, lines 5605-5643

```python
def update_post_entity_path(
    original_path: str,
    shortcode: str,
    new_datetime: datetime | None = None,
) -> str:
    # Line 5618-5619: If no datetime provided, uses datetime.now()
    if new_datetime is None:
        new_datetime = datetime.now()
    
    new_date = new_datetime.strftime("%Y%m%d")
    new_time = new_datetime.strftime("%H%M")
    
    # Creates: post_entity_{profile}_{shortcode}_{YYYYMMDD}_{HHMM}.jsonl
    new_filename = f"post_entity_{profile}_{shortcode}_{new_date}_{new_time}.jsonl"
    return os.path.join(dir_path, new_filename)
```

**Result**: Each post gets its own file:
- `post_entity_job_abc123_xyz789_20260108_1435.jsonl`
- `post_entity_job_abc123_def456_20260108_1436.jsonl`

### 2. Placeholder Analysis

#### Available Placeholders in `expand_paths()`
**Location**: `src/igscraper/config.py`, `expand_paths()`, lines 203-255

**Supported placeholders**:
- `{output_dir}` - from `data.output_dir`
- `{date}` - from substitutions (computed once: `YYYYMMDD`)
- `{datetime}` - from substitutions (computed once: `YYYYMMDD_HHMM`)
- `{target_profile}` - from `main.target_profile` (set to `run_name_for_url_file`)

**Missing placeholders**:
- ❌ `{run_id}` - NOT available
- ❌ `{job_id}` - NOT available
- ❌ `{post_shortcode}` - NOT available at expansion time (only added later via `update_post_entity_path()`)
- ❌ `{timestamp}` - NOT available (only `{datetime}` which is minute-precision)

#### Path Template in config.toml
**Location**: `config.toml`, lines 119-123

```toml
post_entity_path = "{output_dir}/{date}/{target_profile}/post_entity_{target_profile}_{datetime}.jsonl"
metadata_path = "{output_dir}/{date}/{target_profile}/metadata_{target_profile}.jsonl"
```

### 3. expand_paths() Call Frequency

**Called**: **ONCE per pipeline run** (not per post, not per job)

**Evidence**:
- `_scrape_from_url_file()` calls `expand_paths()` once at line 195
- Paths are expanded before any posts are scraped
- `update_post_entity_path()` modifies the filename but keeps the directory structure

### 4. upload_and_enqueue() File Paths

**Location**: `src/igscraper/backends/selenium_backend.py`, `on_comments_batch_ready()`, line 1344-1348

```python
def on_comments_batch_ready(self, local_jsonl_path: str) -> None:
    gcs_uri = self.uploader.upload_and_enqueue(
        local_path=local_jsonl_path,  # Uses self.config.data.post_entity_path
        kind="comment",
    )
```

**Called from**: Line 1602
```python
self.on_comments_batch_ready(self.config.data.post_entity_path)
```

**Path used**: The `post_entity_path` that was updated by `update_post_entity_path()` for each post.

**Result**: Each post uploads its own distinct file (due to shortcode in filename).

### 5. Shared Files and Collision Analysis

#### Files That Are Shared (Potential Collisions)

1. **`metadata_path`** - **SHARED ACROSS ALL POSTS IN SAME RUN**
   - Path: `outputs/{date}/{target_profile}/metadata_{target_profile}.jsonl`
   - **NO shortcode in filename**
   - **NO per-post datetime update**
   - **RISK**: Multiple posts in same run append to same file ✅ (by design)
   - **RISK**: Multiple jobs with same `run_name_for_url_file` will overwrite each other ❌ (BUG)

2. **`tmp_path`** - **SHARED ACROSS ALL POSTS IN SAME RUN**
   - Path: `outputs/{date}/{target_profile}/scrape_results_tmp_{target_profile}_{datetime}.jsonl`
   - Uses initial `{datetime}` from pipeline start
   - **RISK**: Multiple posts append to same temp file ✅ (by design)
   - **RISK**: Multiple jobs with same `run_name` and same minute will collide ❌ (BUG)

3. **`posts_path`** - **SHARED ACROSS ALL POSTS IN SAME RUN**
   - Path: `outputs/{date}/{target_profile}/posts_{target_profile}_{datetime}.txt`
   - **RISK**: Multiple jobs with same `run_name` and same minute will overwrite ❌ (BUG)

#### Files That Are Per-Post (No Collisions)

1. **`post_entity_path`** - **UNIQUE PER POST**
   - Updated by `update_post_entity_path()` with shortcode
   - Format: `post_entity_{profile}_{shortcode}_{YYYYMMDD}_{HHMM}.jsonl`
   - ✅ Safe: Each post gets unique filename

2. **`profile_path`** - **SHARED PER RUN** (but typically only written once)
   - Path: `outputs/{date}/{target_profile}/profile_data_{target_profile}_{datetime}.jsonl`
   - **RISK**: Multiple jobs with same `run_name` will overwrite ❌ (BUG)

### 6. Thor Worker run_name Generation

**Location**: `thor/src/thor/workers/igscraper_worker.py`, `generate_config_toml()`, line 343

```python
# For POST jobs, run_name_for_url_file is set to:
run_name_for_url_file = f"job_{job['job_id']}"
```

**Result**: Each Thor job gets a unique `run_name_for_url_file` based on `job_id`.

**IMPLICATION**: If Thor is used correctly, each job gets a unique run_name, preventing collisions.

**HOWEVER**: If `run_name_for_url_file` is manually set to the same value across multiple jobs, collisions will occur.

### 7. Bug Identification

#### Bug #1: Shared metadata_path Across Jobs
**Severity**: HIGH
**Location**: `config.toml` line 121, `pipeline.py` line 195

**Problem**: 
- `metadata_path` uses `{target_profile}` and `{datetime}` (minute precision)
- Multiple jobs with same `run_name` in same minute will write to same file
- No job_id in path

**Impact**: Data loss from overwriting

**Fix Required**: Add job_id or unique identifier to path, or ensure run_name is always unique.

#### Bug #2: Shared tmp_path Across Jobs
**Severity**: MEDIUM
**Location**: `config.toml` line 123

**Problem**:
- `tmp_path` uses `{datetime}` with minute precision
- Multiple jobs in same minute will collide

**Impact**: Temp file corruption or data loss

#### Bug #3: Datetime Computed Once Per Pipeline
**Severity**: LOW (mitigated by shortcode in post_entity_path)
**Location**: `pipeline.py` line 180

**Problem**:
- `datetime_now` computed once at pipeline start
- All paths use same datetime value
- If pipeline runs for >1 minute, later posts use stale datetime

**Impact**: Minor - directory structure uses start time, but per-post files get fresh datetime from `update_post_entity_path()`

### 8. Design vs Bug Assessment

| Component | Behavior | Assessment |
|-----------|----------|------------|
| `post_entity_path` per post | Unique file per post (shortcode) | ✅ **By Design** |
| `metadata_path` per run | Shared file for all posts in run | ✅ **By Design** |
| `metadata_path` across jobs | Same path if same run_name | ❌ **BUG** |
| `tmp_path` per run | Shared temp file for run | ✅ **By Design** |
| `tmp_path` across jobs | Same path if same run_name+minute | ❌ **BUG** |
| `datetime` computed once | Single datetime per pipeline | ⚠️ **Design Limitation** |
| No job_id in paths | Paths don't include job identifier | ❌ **BUG** (if not using Thor) |

### 9. Code Locations Summary

| Component | File | Lines | Frequency |
|-----------|------|-------|-----------|
| Initial datetime computation | `pipeline.py` | 180 | Once per pipeline |
| Path expansion | `pipeline.py` | 195 | Once per pipeline |
| Per-post path update | `selenium_backend.py` | 927 | Once per post |
| `update_post_entity_path()` | `utils.py` | 5605-5643 | Once per post |
| `on_comments_batch_ready()` | `selenium_backend.py` | 1344-1348 | Once per post batch |
| `upload_and_enqueue()` | `services/upload_enqueue.py` | 53-126 | Once per post batch |
| Thor run_name generation | `thor/workers/igscraper_worker.py` | 343 | Once per job |

### 10. Recommendations

1. **IMMEDIATE FIX**: Ensure Thor always generates unique `run_name_for_url_file` (already done via `job_{job_id}`)

2. **ENHANCEMENT**: Add `{job_id}` placeholder support in path expansion
   - Modify `expand_paths()` to accept job_id
   - Update Thor worker to pass job_id in substitutions

3. **ENHANCEMENT**: Use second-precision datetime instead of minute-precision
   - Change `datetime_now` format from `"%Y%m%d_%H%M"` to `"%Y%m%d_%H%M%S"`

4. **VALIDATION**: Add check to warn if `run_name_for_url_file` is not unique across concurrent jobs

5. **DOCUMENTATION**: Document that `run_name_for_url_file` must be unique per job

