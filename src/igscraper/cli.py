"""
Command-line interface for the Instagram Profile Scraper.

This script serves as the main entry point for running the scraper from the
command line. It handles parsing command-line arguments and initiating the
scraping pipeline.
"""
import argparse
import sys
from pathlib import Path

# Add the project's 'src' directory to the Python path.
# This ensures that modules can be imported using their full path from 'src'
# (e.g., 'igscraper.utils') regardless of how the script is run.
src_path = Path(__file__).resolve().parent.parent
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

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
    parser = argparse.ArgumentParser(description='Instagram Profile Scraper')
    parser.add_argument('--config', required=True, help='Path to config file')
    args = parser.parse_args()

    pipeline = Pipeline(config_path=args.config)
    pipeline.run()

if __name__ == '__main__':
    main()
