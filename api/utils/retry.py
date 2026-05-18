"""重试工具"""
import logging
import time

logger = logging.getLogger(__name__)


def retry_call(fn, times: int = 3, interval: int = 60, on_retry=None):
    last_exc = None
    for attempt in range(1, times + 1):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            if on_retry:
                on_retry(attempt, e)
            else:
                logger.warning(f"重试 {attempt}/{times} 失败: {e}")
            if attempt < times:
                time.sleep(interval)
    raise last_exc
