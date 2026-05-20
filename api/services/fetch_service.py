"""
拉取最新数据后台任务
使用 module-level 状态 + threading（单用户场景，无需任务队列）
"""
import os
import logging
import threading
from datetime import datetime, timedelta

import pandas as pd

from api.config import settings
from api.schemas.models import FetchStatus
from api.utils.trade_calendar import get_target_trade_date

logger = logging.getLogger(__name__)

# 标杆股：用平安银行（000001）作为"市场是否已最新"的探针
# 选它的原因：A 股代码最早、几乎从未停牌、常年活跃
BENCHMARK_STOCK = "000001"

# 需要拉取的指数（指数源始终使用 tushare，因 ths_daily 仅 tushare 提供）
INDICES = [
    {"ts_code": "000001.SH", "name": "上证指数", "file_key": "idx_000001_SH"},
    {"ts_code": "399001.SZ", "name": "深证成指", "file_key": "idx_399001_SZ"},
    {"ts_code": "399006.SZ", "name": "创业板指", "file_key": "idx_399006_SZ"},
    {"ts_code": "000300.SH", "name": "沪深300", "file_key": "idx_000300_SH"},
    {"ts_code": "000016.SH", "name": "上证50", "file_key": "idx_000016_SH"},
    {"ts_code": "000905.SH", "name": "中证500", "file_key": "idx_000905_SH"},
    {"ts_code": "883957.TI", "name": "同花顺全A指数", "file_key": "idx_883957_TI"},
]

_state: dict = {
    "running": False,
    "source": None,
    "started_at": None,
    "finished_at": None,
    "error": None,
    # 上一次成功完成的目标交易日（用于复用：同一天再触发直接跳过）
    "last_target_date": None,
}
_lock = threading.Lock()              # 保护 _state 字典的读写
_fetch_lock = threading.Lock()        # 拉取互斥锁：全局只允许一个拉取任务同时运行


def get_status() -> FetchStatus:
    with _lock:
        # FetchStatus 字段固定，额外的 last_target_date 不影响 pydantic
        snapshot = {k: v for k, v in _state.items() if k != "last_target_date"}
        return FetchStatus(**snapshot)


def start_fetch_latest(source: str = "akshare") -> dict:
    """
    启动后台拉取任务（互斥锁保证全局只有一个拉取在跑）。
    返回 dict: { started: bool, reason: str, target_date: str }
    - 已有任务持锁：复用，started=False, reason='running'
    - 本次目标日已是最新：跳过，started=False, reason='up_to_date'
    - 新任务启动：started=True, reason='launched'
    """
    target_date = get_target_trade_date()
    target_str = target_date.strftime("%Y-%m-%d")

    # 1) 抢拉取锁；抢不到说明另一个任务正在执行
    if not _fetch_lock.acquire(blocking=False):
        with _lock:
            running_source = _state.get("source")
        logger.info(f"拉取锁被占用，复用进行中的任务（source={running_source}, target={target_str}）")
        return {
            "started": False,
            "reason": "running",
            "target_date": target_str,
            "source": running_source,
        }

    # 2) 已持锁 — 任何提前返回都必须释放
    try:
        if _is_market_up_to_date(target_str):
            with _lock:
                _state["last_target_date"] = target_str
            logger.info(f"市场已是最新（目标 {target_str}），跳过拉取，立即释放锁")
            _fetch_lock.release()
            return {
                "started": False,
                "reason": "up_to_date",
                "target_date": target_str,
                "source": source,
            }

        with _lock:
            _state.update({
                "running": True,
                "source": source,
                "started_at": datetime.now().isoformat(timespec="seconds"),
                "finished_at": None,
                "error": None,
            })

        # 后台线程负责在 finally 中释放 _fetch_lock
        thread = threading.Thread(target=_run_fetch, args=(source, target_date), daemon=True)
        thread.start()
        logger.info(f"拉取任务已启动（source={source}, target={target_str}），锁由后台线程持有")
        return {
            "started": True,
            "reason": "launched",
            "target_date": target_str,
            "source": source,
        }
    except Exception:
        # 同步阶段任何异常都要释放锁，避免死锁
        _fetch_lock.release()
        raise


def _is_market_up_to_date(target_date_str: str) -> bool:
    """
    用标杆股（000001）的本地 CSV 最新日期判断全市场是否已是最新。
    命中则跳过整个拉取流程；未命中则正常走单股增量逻辑。
    """
    csv_path = os.path.join(settings.DATA_DIR, f"{BENCHMARK_STOCK}.csv")
    if not os.path.exists(csv_path):
        return False
    try:
        df = pd.read_csv(csv_path, parse_dates=["date"])
        if df.empty:
            return False
        local_max = df["date"].max().strftime("%Y-%m-%d")
        return local_max >= target_date_str
    except Exception as e:
        logger.debug(f"标杆股 {BENCHMARK_STOCK} 短路检查失败（忽略）: {e}")
        return False


def _run_fetch(source: str, target_date):
    try:
        target_str = target_date.strftime("%Y-%m-%d")
        # 拉取窗口：目标交易日往回 7 天，覆盖周末/节假日触发增量逻辑
        start = (target_date - timedelta(days=7)).strftime("%Y-%m-%d")
        end = target_str

        # 双重保险：进入后台后再检查一次（防止两次触发抢跑）
        if _is_market_up_to_date(target_str):
            logger.info(
                f"市场已是最新（标杆股 {BENCHMARK_STOCK} 本地数据 ≥ {target_str}），跳过本次拉取"
            )
            with _lock:
                _state["last_target_date"] = target_str
            return

        logger.info(f"开始拉取数据：source={source}, 区间 {start} ~ {end}（目标交易日 {target_str}）")

        # 1) 拉个股
        fetcher = _create_fetcher(source)
        fetcher.fetch(start_date=start, end_date=end)

        # 2) 拉指数（始终使用 tushare）
        _fetch_indices(start, end)

        with _lock:
            _state["last_target_date"] = target_str
        logger.info(f"拉取完成：source={source}, target={target_str}")
    except Exception as e:
        logger.exception(f"拉取异常：{e}")
        with _lock:
            _state["error"] = str(e)
    finally:
        with _lock:
            _state["running"] = False
            _state["finished_at"] = datetime.now().isoformat(timespec="seconds")
        # 释放拉取锁，允许下一次触发
        _fetch_lock.release()
        logger.info("拉取锁已释放")


def _fetch_indices(start: str, end: str):
    """拉取上证指数、创业板指、同花顺全A，存到 data/idx_xxx.csv"""
    from api.fetcher.tushare_fetcher import TushareDataFetcher
    fetcher = TushareDataFetcher()
    os.makedirs(settings.DATA_DIR, exist_ok=True)
    ts_start = start.replace("-", "")
    ts_end = end.replace("-", "")

    for idx in INDICES:
        try:
            file_key = idx["file_key"]
            csv_path = os.path.join(settings.DATA_DIR, f"{file_key}.csv")

            # 读本地，计算需补区间（与个股增量逻辑一致）
            local_min = local_max = None
            if os.path.exists(csv_path):
                existing = pd.read_csv(csv_path, parse_dates=["date"])
                if not existing.empty:
                    local_min = existing["date"].min()
                    local_max = existing["date"].max()

            ts_start_ts = pd.to_datetime(ts_start)
            ts_end_ts = pd.to_datetime(ts_end)
            ranges = []
            if local_min is None:
                ranges.append((ts_start, ts_end))
            else:
                if (local_min - ts_start_ts).days >= 3:
                    backfill_end = (local_min - timedelta(days=1)).strftime("%Y%m%d")
                    ranges.append((ts_start, backfill_end))
                if (ts_end_ts - local_max).days >= 1:
                    forward_start = (local_max + timedelta(days=1)).strftime("%Y%m%d")
                    ranges.append((forward_start, ts_end))

            if not ranges:
                logger.info(f"skip {idx['name']} ({idx['ts_code']}) local data already up to date")
                continue

            for r_start, r_end in ranges:
                df = fetcher.fetch_index(idx["ts_code"], r_start, r_end)
                if df is None or df.empty:
                    continue
                # 合并 + 去重 + 排序后保存
                if os.path.exists(csv_path):
                    old = pd.read_csv(csv_path, parse_dates=["date"])
                    combined = pd.concat([old, df], ignore_index=True)
                else:
                    combined = df
                combined = combined.drop_duplicates(subset=["date"], keep="last")
                combined = combined.sort_values("date").reset_index(drop=True)
                combined.to_csv(csv_path, index=False, encoding="utf-8-sig")
                logger.info(f"已更新 {idx['name']} ({idx['ts_code']}): {len(df)} 条新数据")
        except Exception as e:
            logger.warning(f"指数 {idx['ts_code']} 拉取失败: {e}")
            continue


def _create_fetcher(source: str):
    if source == "tushare":
        from api.fetcher.tushare_fetcher import TushareDataFetcher
        return TushareDataFetcher()
    if source == "akshare":
        from api.fetcher.akshare_fetcher import AkShareDataFetcher
        return AkShareDataFetcher()
    if source == "baostock":
        import warnings
        warnings.warn(
            "BaoStock 数据源已弃用（服务器长期不稳定），请改用 --source akshare",
            DeprecationWarning,
            stacklevel=2,
        )
        from api.fetcher.baostock_fetcher import BaoStockDataFetcher
        return BaoStockDataFetcher()
    raise ValueError(f"未知数据源: {source}")
