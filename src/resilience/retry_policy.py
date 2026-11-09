import time
import random
import logging
from typing import Callable, Any, Tuple, Type

logger = logging.getLogger("resilience.retry")

def execute_with_retry(
    func: Callable,
    max_retries: int = 3,
    base_delay_sec: float = 0.1,
    max_delay_sec: float = 2.0,
    retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,),
    *args,
    **kwargs
) -> Any:
    """
    Executes a callable with Exponential Backoff and Full Jitter.
    Formula:
        t_backoff = min(max_delay, base_delay * (2 ** attempt))
        sleep_duration = uniform(0, t_backoff)
    Full Jitter prevents thundering-herd spikes on upstream cloud clusters.
    """
    attempt = 0
    last_exception = None

    while attempt < max_retries:
        try:
            return func(*args, **kwargs)
        except retryable_exceptions as exc:
            attempt += 1
            last_exception = exc
            if attempt >= max_retries:
                logger.warning(f"Exhausted all {max_retries} retries for {func.__name__}: {exc}")
                raise

            # Exponential backoff with Full Jitter
            backoff_cap = min(max_delay_sec, base_delay_sec * (2 ** (attempt - 1)))
            sleep_time = random.uniform(0.0, backoff_cap)
            logger.info(f"Retry {attempt}/{max_retries} for {func.__name__} after {sleep_time:.3f}s (Error: {exc})")
            time.sleep(sleep_time)

    raise last_exception
