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
}
_lock = threading.Lock()


def get_status() -> FetchStatus:
    with _lock:
        return FetchStatus(**_state)


def start_fetch_latest(source: str = "akshare") -> bool:
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


def _run_fetch(source: str):
    try:
        # 计算"目标交易日"——盘前/盘中点击会自动对齐到上一个交易日，避免拉到不完整 K 线
        target_date = get_target_trade_date()
        target_str = target_date.strftime("%Y-%m-%d")
        # 拉取窗口：目标交易日往回 7 天，覆盖周末/节假日触发增量逻辑
        start = (target_date - timedelta(days=7)).strftime("%Y-%m-%d")
        end = target_str

        # 前置短路：标杆股已是最新 → 跳过整个流程
        if _is_market_up_to_date(target_str):
            logger.info(
                f"市场已是最新（标杆股 {BENCHMARK_STOCK} 本地数据 ≥ {target_str}），跳过本次拉取"
            )
            return

        logger.info(f"开始拉取数据：source={source}, 区间 {start} ~ {end}（目标交易日 {target_str}）")

        # 1) 拉个股
        fetcher = _create_fetcher(source)
        fetcher.fetch(start_date=start, end_date=end)

        # 2) 拉指数（始终使用 tushare）
        _fetch_indices(start, end)
    except Exception as e:
        with _lock:
            _state["error"] = str(e)
    finally:
        with _lock:
            _state["running"] = False
            _state["finished_at"] = datetime.now().isoformat(timespec="seconds")


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
