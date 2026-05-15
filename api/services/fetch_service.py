"""
拉取最新数据后台任务
使用 module-level 状态 + threading（单用户场景，无需任务队列）
"""
import threading
from datetime import datetime
from typing import Optional

from api.schemas.models import FetchStatus

_state: dict = {
    "running": False,
    "source": None,
    "started_at": None,
    "finished_at": None,
    "error": None,
}
_lock = threading.Lock()


def get_status() -> FetchStatus:
    with _lock:
        return FetchStatus(**_state)


def start_fetch_latest(source: str = "tushare") -> bool:
    """
    启动后台拉取任务。如果已有任务在跑则返回 False。
    拉取从今天往回 7 天（足以覆盖周末 + 节假日）到今天。
    """
    with _lock:
        if _state["running"]:
            return False
        _state.update({
            "running": True,
            "source": source,
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "finished_at": None,
            "error": None,
        })

    thread = threading.Thread(target=_run_fetch, args=(source,), daemon=True)
    thread.start()
    return True


def _run_fetch(source: str):
    try:
        fetcher = _create_fetcher(source)
        # 拉取 7 天窗口，足以覆盖周末和节假日，触发增量逻辑补到今天
        from datetime import timedelta
        today = datetime.now().date()
        start = (today - timedelta(days=7)).strftime("%Y-%m-%d")
        end = today.strftime("%Y-%m-%d")
        fetcher.fetch(start_date=start, end_date=end)
    except Exception as e:
        with _lock:
            _state["error"] = str(e)
    finally:
        with _lock:
            _state["running"] = False
            _state["finished_at"] = datetime.now().isoformat(timespec="seconds")


def _create_fetcher(source: str):
    if source == "tushare":
        from fetcher.tushare_fetcher import TushareDataFetcher
        return TushareDataFetcher()
    if source == "akshare":
        from fetcher.akshare_fetcher import AkShareDataFetcher
        return AkShareDataFetcher()
    if source == "baostock":
        from fetcher.baostock_fetcher import BaoStockDataFetcher
        return BaoStockDataFetcher()
    raise ValueError(f"未知数据源: {source}")
