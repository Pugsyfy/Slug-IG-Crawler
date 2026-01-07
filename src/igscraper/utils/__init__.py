"""
Utils package - maintains backward compatibility with utils.py module.

This package re-exports all functions from the parent utils.py module and also includes
the video_finalizer module.

Note: When both utils.py and utils/ exist, Python prioritizes the package.
We use importlib to import from the parent utils.py file.
"""
import sys
import importlib.util
from pathlib import Path

# Import everything from the parent utils.py module to maintain backward compatibility
# This allows existing imports like "from igscraper.utils import ..." to continue working
_parent_dir = Path(__file__).parent.parent
_utils_py_path = _parent_dir / "utils.py"

if _utils_py_path.exists():
    # Load utils.py as a module
    spec = importlib.util.spec_from_file_location("igscraper.utils_legacy", _utils_py_path)
    utils_legacy = importlib.util.module_from_spec(spec)
    sys.modules["igscraper.utils_legacy"] = utils_legacy
    spec.loader.exec_module(utils_legacy)
    
    # Re-export everything from utils.py (including private functions for backward compatibility)
    # This maintains full backward compatibility with existing imports
    # Standard Python module attributes to exclude
    _excluded_attrs = {
        "__file__", "__name__", "__doc__", "__package__", "__loader__", 
        "__spec__", "__cached__", "__builtins__", "__path__"
    }
    
    for name in dir(utils_legacy):
        # Include all user-defined names (including private functions like _set_bytestart_zero)
        # Exclude only standard Python module dunder attributes
        if name not in _excluded_attrs:
            try:
                globals()[name] = getattr(utils_legacy, name)
            except (AttributeError, TypeError):
                # Skip attributes that can't be accessed or assigned
                pass

# Also make video_finalizer available
from . import video_finalizer  # noqa: F401

