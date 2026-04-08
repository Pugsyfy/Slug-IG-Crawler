#!/usr/bin/env bash
set -euo pipefail

export PYTHONPATH="$PWD/src:${PYTHONPATH:-}"
VENV_DIR=".venv3.10"   # path to your venv

usage() {
    echo "Usage:"
    echo "  $0                    # run the CLI pipeline (Slug-Ig-Crawler or python -m igscraper)"
    exit 1
}

for arg in "$@"; do
    case $arg in
        -h|--help)
            usage
            ;;
        *)
            echo "Unknown option: $arg"
            usage
            ;;
    esac
done

if [[ ! -d "$VENV_DIR" ]]; then
    echo "!! Virtual environment not found at $VENV_DIR"
    echo "   Create it first with: python3 -m venv $VENV_DIR"
    exit 1
fi

source "$VENV_DIR/bin/activate"

echo "==> Running Python scraper (inside venv)..."
Slug-Ig-Crawler --config config.toml

echo "==> Done."
