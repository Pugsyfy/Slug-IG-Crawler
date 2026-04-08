"""
Command-line interface for slug-ig-crawler.

This script serves as the main entry point for running the scraper from the
command line. It handles parsing command-line arguments and initiating the
scraping pipeline.
"""
import argparse
import sys
from pathlib import Path

# When running from a source checkout (`src/igscraper/...`), add `src/` so imports work.
# When installed as a wheel, site-packages already provides `igscraper`.
_pkg_dir = Path(__file__).resolve().parent
_src = _pkg_dir.parent
if _src.name == "src" and str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from igscraper.pipeline import Pipeline

def main():
    """
    Parses command-line arguments and starts the scraping pipeline.

    This function sets up the argument parser to accept the necessary command-line
    options and then calls the main `run_pipeline` function with the provided
    configuration.

    Arguments:
        --config (str): Required. Path to the configuration file (e.g., 'config.toml').
    """
    parser = argparse.ArgumentParser(description='slug-ig-crawler')
    parser.add_argument('--config', required=True, help='Path to config file')
    args = parser.parse_args()

    pipeline = Pipeline(config_path=args.config)
    pipeline.run()

if __name__ == '__main__':
    main()
