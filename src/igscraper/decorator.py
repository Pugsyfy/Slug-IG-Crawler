import functools
import traceback
from igscraper.logger import get_logger


def try_except(
    exception_types=(Exception,),
    reraise=False,
    default=None,
    log_traceback=True,
    log_error=False,
):
    """
    Decorator that wraps methods/functions with try/except and allows explicit control over logging.

    Args:
        exception_types: Tuple of exception types to catch. Default: (Exception,)
        reraise: Whether to re-raise the exception after logging. Default: False
        default: Value to return if an exception occurs. Default: None
        log_traceback: Whether to include the full traceback. Default: True
        log_error: If True, logs the error message (and traceback if enabled). Default: False

    Example:
        @try_except(log_error=True, default="error")
        def foo(): raise RuntimeError("boom!")
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Use self.logger if available; fallback to module logger that respects config.toml
            logger = None
            if args and hasattr(args[0], "logger"):
                logger = getattr(args[0], "logger", None)
            if logger is None:
                logger = get_logger(func.__module__)

            try:
                return func(*args, **kwargs)

            except exception_types as e:
                if log_error:
                    if log_traceback:
                        tb = traceback.format_exc()
                        logger.error(f"Exception in {func.__qualname__}:\n{tb}")
                    else:
                        logger.error(f"Exception in {func.__qualname__}: {e}")

                if reraise:
                    raise
                return default

        return wrapper
    return decorator
