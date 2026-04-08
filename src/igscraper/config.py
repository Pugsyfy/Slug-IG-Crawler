import toml
from pydantic import Field, ValidationError, BaseModel, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional, Callable, Any, List
from igscraper.logger import configure_root_logger, get_logger
from pathlib import Path
import logging
from pydantic import PrivateAttr
from igscraper.models.registry_parser import GraphQLModelRegistry

PROJECT_ROOT = Path.cwd()  # since you always start in root


def get_default_cached_config_path() -> Path:
    """
    Default user config location when ``--config`` is omitted: ``~/.slug/config.toml``.

    The file may not exist yet; callers should check before loading.
    """
    from igscraper.paths import get_cached_config_path

    return get_cached_config_path()


# Suppress noisy third-party library loggers (set before config loads)
# These are library-specific settings, independent of config.toml [logging] section
# They only affect external library noise, not application logging
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("selenium.webdriver.remote").setLevel(logging.INFO)

def resolve_path(path_str: str) -> Path:
    """
    Resolves a string path into an absolute Path object.

    If the path is relative, it is resolved against the project's root directory.
    If it's already absolute, it's returned as is.

    Args:
        path_str: The path string from the configuration file.

    Returns:
        An absolute Path object.
    """
    path = Path(path_str)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


class ProfileTarget(BaseModel):
    """Represents a single profile to be scraped."""
    name: str
    num_posts: int = Field(..., gt=0)

class MainConfig(BaseSettings):
    """
    Configuration settings related to the main application logic and scraping behavior.
    """
    # --- Scraping Mode ---
    # List of target profiles to scrape in mode 1.
    mode: int = 1  # 1 = profile mode, 2 = URL file mode
    # To scrape profiles (can be empty if using urls_filepath)
    target_profiles: List[ProfileTarget] = []
    # A name for the run when scraping from a URL file.
    run_name_for_url_file: str = "url_file_run"
    # Internal field for the currently processed profile, not for user config.
    target_profile: Optional[str] = None
    # If True, runs the browser in headless mode (no GUI).
    headless: bool = True
    enable_screenshots: bool = False
    use_docker: bool = False
    # Optional paths when env vars are unset (see selenium_backend). Precedence is always:
    # CHROME_BIN / CHROMEDRIVER_BIN env → (if local) these fields → local defaults; (if Docker) image paths.
    chrome_binary_path: Optional[str] = None
    chromedriver_binary_path: Optional[str] = None
    # Minimum random delay (in seconds) between batches of requests.
    rate_limit_seconds_min: int = 2
    # Maximum random delay (in seconds) between batches of requests.
    rate_limit_seconds_max: int = 5
    # General-purpose retry count for various operations.
    max_retries: int = 3
    # Number of posts to open and scrape in a single batch.
    batch_size: int = 4
    # If True, the batch size will be randomized slightly to appear more human.
    randomize_batch: bool = False
    # Optional user-agent string for the browser.
    user_agent: Optional[str] = None
    # Duration (in seconds) for the simulated human mouse movement.
    human_mouse_move_duration: float = 0.5
    # Number of retries when scrolling the main profile page if no new content loads.
    page_scroll_retries: int = 3
    # Save scraped data to the final file after every N posts.
    save_every: int = 5
    # Number of retries when scrolling comments if no new content loads.
    comments_scroll_retries: int = 1
    # Number of scroll steps to perform when collecting comments.
    comment_scroll_steps: int = 30

    # fetch comments
    fetch_comments: bool = True

    gcs_bucket_name: str = "crawled_data"
    # 1 = upload JSONL to GCS and insert gs://... into Postgres; 0 = skip GCS, insert absolute local path.
    push_to_gcs: int = Field(1, description="Must be 0 or 1.")

    @field_validator("push_to_gcs")
    @classmethod
    def _push_to_gcs_binary(cls, v: int) -> int:
        if v not in (0, 1):
            raise ValueError("push_to_gcs must be 0 or 1")
        return v

    # Credentials can be loaded from env vars (e.g., IGSCRAPER_USERNAME)
    # The alias allows the TOML file to use 'instagram_username'.
    username: Optional[str] = Field(None, alias='instagram_username')
    password: Optional[str] = Field(None, alias='instagram_password')

    # registry
    registry: Optional[GraphQLModelRegistry] = None

    # flag is using captured requests
    scrape_using_captured_requests: bool = True

    fetch_replies: bool = True
    max_comments: int = 20
    # Maximum number of consecutive batches with no new comments before stopping comment extraction
    comment_no_new_retries: int = 3
    # Consumer ID for identifying the scraper instance in logs
    consumer_id: Optional[str] = None

class DataConfig(BaseSettings):
    """Configuration settings related to file paths and data storage."""
    # Directory where all output files will be stored.
    output_dir: str = "outputs"
    shot_dir: str
    # Optional: Path to a file containing post URLs to scrape, one per line.
    urls_filepath: Optional[str] = None
    # Path to the file for storing collected post URLs. Supports placeholders.
    posts_path: str
    # Path to the final JSONL file for storing scraped post metadata. Supports placeholders.
    metadata_path: str
    # Path to the file for logging URLs of skipped posts. Supports placeholders.
    skipped_path: str
    # Path to the temporary file for intermediate scrape results. Supports placeholders.
    tmp_path: str
    # Path to the browser cookie file for authentication.
    cookie_file: str
    # Path to the directory where downloaded media files will be stored. Supports placeholders.
    media_path: str
    # schema path for the keys to pull out of data
    schema_path: str
    # data related to extracted pydantic models(with extras)
    models_path: str
    # required flatten schema data
    extracted_data_path: str
    # save graphql keys - Temp
    graphql_keys_path: str
    ### keys ####
    profile_page_data_key: list[str]
    post_page_data_key: list[str]
    ## paths to save extracted entities
    post_entity_path: str
    profile_path: str


class LoggingConfig(BaseSettings):
    """Configuration settings for logging."""
    # The logging level (e.g., "DEBUG", "INFO", "WARNING").
    level: str
    # Optional: Directory to save log files.
    log_dir: Optional[str] = None
    log_format: str
    date_format: str

class TraceConfig(BaseSettings):
    """Configuration for trace/tracking information."""
    thor_worker_id: str  # Required, non-empty

class Config(BaseSettings):
    """
    The main configuration model that aggregates all other configuration sections.

    It is configured to load environment variables with the prefix "IGSCRAPER_".
    """
    model_config = SettingsConfigDict(env_prefix="IGSCRAPER_", case_sensitive=False)

    main: MainConfig
    data: DataConfig
    logging: LoggingConfig
    trace: TraceConfig
    _driver = PrivateAttr(default=None)

def load_config(path: str) -> Config:
    """
    Loads configuration from a TOML file, sets up logging, and processes paths.

    Args:
        path: The path to the TOML configuration file.

    Returns:
        A fully validated and processed Config object.
    """
    with open(path, "r") as f:
        data = toml.load(f)

    # Determine logging configuration from the raw TOML data
    log_level = data.get("logging", {}).get("level", "INFO")
    log_dir_path_str = data.get("logging", {}).get("log_dir")

    if log_dir_path_str:
        log_dir = resolve_path(log_dir_path_str)
    else:
        # Fallback to the 'outputs/logs' directory if not specified
        output_dir = data.get("data", {}).get("output_dir", "outputs")
        log_dir = resolve_path(output_dir) / "logs"

    # Configure logging once, using logging level from TOML
    # and placing logs in the specified directory.
    configure_root_logger(data)
    # configure_root_logger(level=log_level, log_dir=log_dir)

    logger = get_logger("config")
    logger.debug("Configuration loaded successfully")
    
    # Note: [trace] validation is deferred to Pipeline.__init__ to avoid
    # import-time failures for loaders that omit trace (e.g. some test helpers)
    # If trace section is missing, add a dummy one to satisfy Pydantic schema
    if "trace" not in data:
        data["trace"] = {"thor_worker_id": "not-validated-yet"}
    
    # Return the config object without path expansion.
    # Path expansion will be handled per-profile in the pipeline.
    return Config(**data)


def expand_paths(section: BaseSettings, substitutions: dict | None = None, depth: int = 0) -> None:
    indent = "  " * depth
    # print(f"{indent}>> Entering expand_paths for: {section.__class__.__name__}")

    def flatten_model(model: BaseModel | dict) -> dict:
        flat = {}
        if isinstance(model, BaseModel):
            items = model.model_dump()
        else:
            items = model

        for k, v in items.items():
            if isinstance(v, (BaseModel, dict)):
                flat.update(flatten_model(v))
            else:
                flat[k] = v
        return flat

    if substitutions is None:
        substitutions = {}

    all_values = {**flatten_model(section), **substitutions}
    # print(f"{indent}Available substitutions: {list(all_values.keys())}")

    # iterate over actual model attributes, not dumped dicts
    for field_name, value in section.__dict__.items():
        # print(f"{indent}Processing '{field_name}' -> {value!r}")
        if isinstance(value, str):
            prev, expanded = None, value
            while expanded != prev and "{" in expanded and "}" in expanded:
                prev = expanded
                try:
                    expanded = expanded.format(**all_values)
                    # print(f"{indent}  Expanded to: {expanded}")
                except KeyError as e:
                    # print(f"{indent}  Missing substitution for {e.args[0]} in '{field_name}'")
                    break

            try:
                expanded_path = resolve_path(expanded)
                setattr(section, field_name, str(expanded_path))
                all_values[field_name] = str(expanded_path)
                # print(f"{indent}  Resolved to path: {expanded_path}")
            except Exception:
                setattr(section, field_name, expanded)
                all_values[field_name] = expanded

        elif isinstance(value, BaseSettings):
            # print(f"{indent}Descending into nested model '{field_name}'")
            expand_paths(value, all_values, depth + 1)

    # print(f"{indent}<< Finished expand_paths for: {section.__class__.__name__}\n")
