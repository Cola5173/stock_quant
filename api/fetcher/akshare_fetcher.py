"""
AkShare 数据获取模块
使用 AkShare 数据源获取股票数据（免费，基于东方财富）
"""
import os
import time
import random
import logging
import contextlib
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Set
from datetime import datetime, timedelta

import pandas as pd

from .fetcher import DataFetcher
from api.schemas.kline_constants import KLineConstants
from api.config import settings
from api.utils.utils import _normalize_stock_code

logger = logging.getLogger(__name__)

# 请求间隔（秒），避免被东方财富限流
REQUEST_INTERVAL_MIN = 3.0
REQUEST_INTERVAL_MAX = 5.0

# 并发拉取的 worker 数（保守值，单 worker 仍保留 3~5s sleep）
FETCH_WORKERS = 4


def _random_sleep():
    """随机等待 3~5 秒，降低被限流风险"""
    time.sleep(random.uniform(REQUEST_INTERVAL_MIN, REQUEST_INTERVAL_MAX))


@contextlib.contextmanager
def _no_proxy():
    """临时禁用代理（东方财富接口走代理会失败）"""
    saved = {k: os.environ.get(k) for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "NO_PROXY", "no_proxy")}
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        os.environ.pop(k, None)
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class AkShareDataFetcher(DataFetcher):
    """使用 AkShare 数据源（免费，基于东方财富）"""

    def __init__(self):
        super().__init__()
        try:
            import akshare as ak
            self.ak = ak
        except ImportError:
            raise ImportError("请先安装 akshare: pip install akshare")

    def get_last_trade_date(self) -> str:
        """获取最近的交易日"""
        try:
            with _no_proxy():
                df = self.ak.stock_zh_a_hist(
                    symbol="000001",
                    period="daily",
                    start_date=(datetime.now().strftime('%Y%m%d')),
                    end_date=datetime.now().strftime('%Y%m%d'),
                    adjust="qfq"
                )
            if not df.empty:
                return df["日期"].iloc[-1]
        except Exception:
            pass

        # 回退：往前查找
        for days_back in range(1, 10):
            try:
                test_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y%m%d')
                with _no_proxy():
                    df = self.ak.stock_zh_a_hist(
                        symbol="000001",
                        period="daily",
                        start_date=test_date,
                        end_date=test_date,
                        adjust="qfq"
                    )
                if not df.empty:
                    return df["日期"].iloc[-1]
            except Exception:
                continue

        return datetime.now().strftime('%Y-%m-%d')

    def fetch(self, start_date: Optional[str] = None, end_date: Optional[str] = None) -> None:
        """
        批量下载股票数据（并发版）
        :param start_date: 起始日期 YYYY-MM-DD
        :param end_date: 结束日期 YYYY-MM-DD
        """
        from tqdm import tqdm

        os.makedirs(settings.DATA_DIR, exist_ok=True)

        # 获取股票列表
        print("step 1.1: ----> 获取所有A股股票列表...")
        stock_codes = self._get_all_stock_codes()
        if not stock_codes:
            print("未获取到股票列表")
            return
        print(f"共 {len(stock_codes)} 只股票")

        # 转换日期格式（YYYY-MM-DD -> YYYYMMDD）
        ak_start = start_date.replace("-", "") if start_date else "20240101"
        ak_end = end_date.replace("-", "") if end_date else datetime.now().strftime('%Y%m%d')

        print(f"step 1.2: ----> 开始下载K线数据 [{start_date} ~ {end_date}]，并发 {FETCH_WORKERS}...")

        sorted_codes = sorted(stock_codes, key=_normalize_stock_code)
        counters = {"success": 0, "fail": 0, "skipped": 0}
        counters_lock = threading.Lock()

        with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
            futures = {
                pool.submit(self._fetch_one_incremental, code, ak_start, ak_end): code
                for code in sorted_codes
            }
            with tqdm(total=len(futures), desc="下载数据") as pbar:
                for fut in as_completed(futures):
                    code = futures[fut]
                    try:
                        status = fut.result()
                    except Exception as e:
                        status = "fail"
                        logger.debug(f"下载 {code} 异常: {e}")
                    with counters_lock:
                        counters[status] = counters.get(status, 0) + 1
                    pbar.update(1)
                    pbar.set_postfix(ok=counters["success"], skip=counters["skipped"], fail=counters["fail"])

        print("step 1.3: ----> 下载完成！")
        print(f"  - 成功: {counters['success']} 只股票")
        print(f"  - 跳过: {counters['skipped']} 只股票（本地已是最新）")
        print(f"  - 失败: {counters['fail']} 只股票")

    def _fetch_one_incremental(self, stock_code: str, ak_start: str, ak_end: str) -> str:
        """
        单只股票增量拉取的完整流程：
        1. 计算需要补的区间（最多两段：backfill + forward）
        2. 命中跳过条件直接 return "skipped"
        3. 调用 _fetch_single_stock + _save_stock_data
        :return: "success" | "skipped" | "fail"
        """
        try:
            symbol = _normalize_stock_code(stock_code)
            ak_start_ts = pd.to_datetime(ak_start)
            ak_end_ts = pd.to_datetime(ak_end)
            existing_df = self._load_stock_data(symbol)

            ranges = []
            if existing_df.empty:
                ranges.append((ak_start, ak_end))
            else:
                local_min = existing_df[KLineConstants.DATE].min()
                local_max = existing_df[KLineConstants.DATE].max()
                if ak_start_ts < local_min:
                    backfill_end = (local_min - timedelta(days=1)).strftime('%Y%m%d')
                    ranges.append((ak_start, backfill_end))
                if ak_end_ts > local_max:
                    forward_start = (local_max + timedelta(days=1)).strftime('%Y%m%d')
                    ranges.append((forward_start, ak_end))

            if not ranges:
                return "skipped"

            fetched = False
            for r_start, r_end in ranges:
                df = self._fetch_single_stock(symbol, r_start, r_end)
                if df is not None and not df.empty:
                    self._save_stock_data(symbol, df)
                    fetched = True
            return "success" if fetched else "skipped"
        except Exception as e:
            logger.debug(f"下载 {stock_code} 失败: {e}")
            return "fail"

    def _fetch_single_stock(self, symbol: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """
        获取单只股票的日线数据
        :param symbol: 纯数字代码（如 600000）
        :param start_date: YYYYMMDD
        :param end_date: YYYYMMDD
        """
        start_dt = pd.to_datetime(start_date)
        end_dt = pd.to_datetime(end_date)
        if (end_dt - start_dt).days > 365 * 2:
            return self._fetch_single_stock_chunked(symbol, start_date, end_date)

        import requests
        max_retries = 3
        last_err = None
        for attempt in range(max_retries):
            try:
                _random_sleep()
                with _no_proxy():
                    df = self.ak.stock_zh_a_hist(
                        symbol=symbol,
                        period="daily",
                        start_date=start_date,
                        end_date=end_date,
                        adjust="qfq"
                    )

                if df is None or df.empty:
                    return None

                return self._normalize_hist_df(df, symbol)

            except (requests.exceptions.ConnectionError,
                    requests.exceptions.ChunkedEncodingError,
                    requests.exceptions.Timeout,
                    requests.exceptions.ProxyError,
                    ConnectionResetError) as e:
                last_err = e
                wait = 2 ** attempt
                logger.warning(f"获取 {symbol} 网络失败（{attempt + 1}/{max_retries}），{wait}s 后重试: {e}")
                time.sleep(wait)
            except Exception as e:
                logger.debug(f"获取 {symbol} 数据失败: {e}")
                return None

        logger.warning(f"获取 {symbol} 重试 {max_retries} 次仍失败: {last_err}")
        return None

    def _fetch_single_stock_chunked(self, symbol: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """分段获取超长日期范围的数据（每段最多2年）"""
        start_dt = pd.to_datetime(start_date)
        end_dt = pd.to_datetime(end_date)
        chunks = []

        cursor = start_dt
        while cursor < end_dt:
            chunk_end = min(cursor + timedelta(days=365 * 2), end_dt)
            chunk_start_str = cursor.strftime('%Y%m%d')
            chunk_end_str = chunk_end.strftime('%Y%m%d')

            try:
                with _no_proxy():
                    df = self.ak.stock_zh_a_hist(
                        symbol=symbol,
                        period="daily",
                        start_date=chunk_start_str,
                        end_date=chunk_end_str,
                        adjust="qfq"
                    )
                if df is not None and not df.empty:
                    print(f"  分段 [{chunk_start_str}~{chunk_end_str}] 获取 {len(df)} 条")
                    chunks.append(df)
                else:
                    print(f"  分段 [{chunk_start_str}~{chunk_end_str}] 无数据")
            except Exception as e:
                print(f"  分段 [{chunk_start_str}~{chunk_end_str}] 失败: {e}")

            cursor = chunk_end + timedelta(days=1)
            _random_sleep()

        if not chunks:
            return None

        combined = pd.concat(chunks, ignore_index=True)
        return self._normalize_hist_df(combined, symbol)

    def _normalize_hist_df(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """将 AkShare 返回的中文列名 DataFrame 标准化"""
        column_map = {
            "日期": KLineConstants.DATE,
            "开盘": KLineConstants.OPEN,
            "收盘": KLineConstants.CLOSE,
            "最高": KLineConstants.HIGH,
            "最低": KLineConstants.LOW,
            "成交量": KLineConstants.VOLUME,
            "成交额": "amount",
            "振幅": "amplitude_pct",
            "涨跌幅": "pctChg",
            "涨跌额": "change",
            "换手率": "turn",
        }
        df = df.rename(columns=column_map)

        df[KLineConstants.DATE] = pd.to_datetime(df[KLineConstants.DATE])
        df["code"] = symbol
        df["stock_code"] = symbol

        if "preclose" not in df.columns:
            df["preclose"] = df[KLineConstants.CLOSE].shift(1)

        df = df.sort_values(KLineConstants.DATE).drop_duplicates(subset=[KLineConstants.DATE], keep='last').reset_index(drop=True)
        return df

    def _fetch_spot_em_with_retry(self, max_retries: int = 3) -> Optional[pd.DataFrame]:
        """
        调用 ak.stock_zh_a_spot_em() 获取全市场实时行情，带指数退避重试。
        东方财富接口偶发限流/连接被重置，单次失败不代表真的拿不到。
        """
        import requests

        last_err = None
        for attempt in range(max_retries):
            try:
                with _no_proxy():
                    return self.ak.stock_zh_a_spot_em()
            except (requests.exceptions.ConnectionError,
                    requests.exceptions.ChunkedEncodingError,
                    requests.exceptions.Timeout,
                    ConnectionResetError) as e:
                last_err = e
                wait = 2 ** attempt
                logger.warning(f"获取全市场行情失败（第 {attempt + 1}/{max_retries} 次），{wait}s 后重试: {e}")
                time.sleep(wait)
            except Exception as e:
                last_err = e
                logger.warning(f"获取全市场行情异常（第 {attempt + 1}/{max_retries} 次）: {e}")
                time.sleep(2 ** attempt)

        if last_err is not None:
            raise last_err
        return None

    def get_all_stock_list(self, filter_st: bool = True,
                           cache_file: str = None) -> List[str]:
        """
        获取全市场A股股票列表
        :param filter_st: 是否过滤ST股票
        :param cache_file: 缓存文件路径
        :return: 股票代码列表（纯数字格式）
        """
        if cache_file is None:
            cache_file = settings.STOCK_LIST_CACHE

        try:
            print("正在获取全市场A股股票列表...")
            df = self._fetch_spot_em_with_retry()

            if df is None or df.empty:
                print("获取股票列表失败：返回数据为空")
                return []

            stock_list = []
            for _, row in df.iterrows():
                code = str(row["代码"])
                name = str(row.get("名称", ""))

                # 只保留沪深A股
                if not (code.startswith("6") or code.startswith("0") or code.startswith("3")):
                    continue

                # 过滤ST
                if filter_st and ("ST" in name or "st" in name):
                    continue

                stock_list.append(code)

            print(f"获取到 {len(stock_list)} 只A股股票")

            # 缓存
            if stock_list and cache_file:
                os.makedirs(os.path.dirname(cache_file), exist_ok=True)
                with open(cache_file, 'w', encoding='utf-8') as f:
                    for code in stock_list:
                        f.write(f"{code}\n")
                print(f"股票列表已缓存到 {cache_file}")

            return stock_list

        except Exception as e:
            print(f"获取股票列表失败: {e}")
            return []
