"""Slug-Ig-Crawler (PyPI distribution name: ``slug-ig-crawler``; import package: ``igscraper``)."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("slug-ig-crawler")
except PackageNotFoundError:
    __version__ = "0.0.0"

__all__ = ["__version__"]
