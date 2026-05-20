"""
Tushare 数据获取模块
使用 Tushare Pro 接口，通过 config.tushare_client 统一初始化
"""
import os
import io
import time
import logging
import contextlib
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional
from datetime import datetime, timedelta

import pandas as pd

from .fetcher import DataFetcher
from api.schemas.kline_constants import KLineConstants
from api.config import settings
from .tushare_client import pro, ts
from api.utils.utils import _normalize_stock_code

logger = logging.getLogger(__name__)

REQUEST_INTERVAL = 0.5
FETCH_WORKERS = 4


def _to_ts_code(stock_code: str) -> str:
    """纯数字代码 → Tushare 格式（600000 → 600000.SH）"""
    code = _normalize_stock_code(stock_code)
    if code.startswith("6"):
        return f"{code}.SH"
    if code.startswith(("0", "3")):
        return f"{code}.SZ"
    if code.startswith(("4", "8")):
        return f"{code}.BJ"
    return code


class TushareDataFetcher(DataFetcher):
    """Tushare Pro 数据源"""

    def __init__(self):
        super().__init__()
        self.ts = ts
        self.pro = pro

    def get_last_trade_date(self) -> str:
        """通过 Tushare 交易日历获取最近交易日"""
        try:
            today = datetime.now().strftime("%Y%m%d")
            start = (datetime.now() - timedelta(days=15)).strftime("%Y%m%d")
            df = self.pro.trade_cal(
                exchange="SSE",
                start_date=start,
                end_date=today,
                is_open="1",
            )
            if df is not None and not df.empty:
                cal_date = df["cal_date"].max()
                return f"{cal_date[:4]}-{cal_date[4:6]}-{cal_date[6:8]}"
        except Exception as e:
            logger.debug(f"Tushare 交易日历获取失败: {e}")

        return datetime.now().strftime("%Y-%m-%d")

    def get_all_stock_list(self, filter_st: bool = True,
                           cache_file: str = None) -> List[str]:
        """
        获取全市场 A 股列表
        :return: 纯数字代码列表
        """
        if cache_file is None:
            cache_file = settings.STOCK_LIST_CACHE

        try:
            print("正在获取全市场A股股票列表（Tushare）...")
            df = self.pro.stock_basic(
                exchange="",
                list_status="L",
                fields="ts_code,symbol,name,market,list_status",
            )

            if df is None or df.empty:
                print("Tushare 返回股票列表为空")
                return []

            stock_list = []
            for _, row in df.iterrows():
                code = str(row["symbol"])
                name = str(row.get("name", ""))

                if not (code.startswith("6") or code.startswith("0") or code.startswith("3")):
                    continue
                if filter_st and ("ST" in name or "st" in name):
                    continue

                stock_list.append(code)

            print(f"获取到 {len(stock_list)} 只 A 股股票")

            if stock_list and cache_file:
                os.makedirs(os.path.dirname(cache_file), exist_ok=True)
                with open(cache_file, "w", encoding="utf-8") as f:
                    for code in stock_list:
                        f.write(f"{code}\n")
                print(f"股票列表已缓存到 {cache_file}")

            return stock_list

        except Exception as e:
            print(f"Tushare 获取股票列表失败: {e}")
            return []

    def fetch(self, start_date: Optional[str] = None,
              end_date: Optional[str] = None,
              symbols: Optional[list] = None) -> dict:
        """批量下载股票日线数据（多线程并发）。

        :param start_date: 开始日期 YYYY-MM-DD
        :param end_date: 结束日期 YYYY-MM-DD
        :param symbols: 指定股票列表（None 时拉取全市场）。用于失败重试场景。
        :return: {"success": int, "failed": int, "skipped": int, "fail_log_path": Optional[str], "failures": list}
        """
        os.makedirs(settings.DATA_DIR, exist_ok=True)

        if symbols:
            stock_codes = symbols
            logger.info(f"重试模式：使用传入的 {len(stock_codes)} 只股票")
        else:
            logger.info("获取所有 A 股股票列表...")
            stock_codes = self._get_all_stock_codes()
            if not stock_codes:
                logger.warning("未获取到股票列表")
                return {"success": 0, "failed": 0, "skipped": 0, "fail_log_path": None, "failures": []}
            logger.info(f"共 {len(stock_codes)} 只股票")

        ts_start = start_date.replace("-", "") if start_date else "20240101"
        ts_end = end_date.replace("-", "") if end_date else datetime.now().strftime("%Y%m%d")

        logger.info(f"开始下载 K 线数据 [{start_date} ~ {end_date}]，并发 {FETCH_WORKERS} 线程")

        counters = {"success": 0, "failed": 0, "skipped": 0, "done": 0}
        failures: list = []
        counter_lock = threading.Lock()
        total = len(stock_codes)

        def worker(stock_code: str):
            symbol = _normalize_stock_code(stock_code)
            try:
                result = self._fetch_one_incremental(symbol, ts_start, ts_end)
                with counter_lock:
                    counters["done"] += 1
                    if result == "success":
                        counters["success"] += 1
                    elif result == "skipped":
                        counters["skipped"] += 1
                    else:
                        counters["failed"] += 1
                        failures.append(result)
                    done = counters["done"]
                if done % 200 == 0 or done == total:
                    logger.info(f"  进度 {done}/{total}  成功 {counters['success']}  跳过 {counters['skipped']}  失败 {counters['failed']}")
            except Exception as e:
                with counter_lock:
                    counters["done"] += 1
                    counters["failed"] += 1
                    failures.append({
                        "symbol": symbol,
                        "reason": f"{type(e).__name__}: {e}",
                        "ranges": [f"{ts_start}-{ts_end}"],
                    })

        with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
            futures = [pool.submit(worker, code) for code in sorted(stock_codes, key=_normalize_stock_code)]
            for fut in as_completed(futures):
                pass

        logger.info(f"首轮完成：成功 {counters['success']}  跳过 {counters['skipped']}  失败 {counters['failed']}")

        # 对失败标的进行最多 5 轮重试
        max_retry_rounds = 5
        for retry_round in range(1, max_retry_rounds + 1):
            if not failures:
                break
            retry_symbols = [f["symbol"] for f in failures]
            logger.info(f"第 {retry_round} 轮重试：{len(retry_symbols)} 只失败标的")
            failures = []
            retry_done = 0

            def retry_worker(stock_code: str):
                nonlocal retry_done
                symbol = _normalize_stock_code(stock_code)
                try:
                    result = self._fetch_one_incremental(symbol, ts_start, ts_end)
                    with counter_lock:
                        retry_done += 1
                        if result == "success":
                            counters["success"] += 1
                            counters["failed"] -= 1
                        elif result == "skipped":
                            counters["skipped"] += 1
                            counters["failed"] -= 1
                        else:
                            failures.append(result)
                except Exception as e:
                    with counter_lock:
                        retry_done += 1
                        failures.append({
                            "symbol": symbol,
                            "reason": f"{type(e).__name__}: {e}",
                            "ranges": [f"{ts_start}-{ts_end}"],
                        })

            time.sleep(2)  # 重试前等一下，让代理恢复
            with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
                futs = [pool.submit(retry_worker, s) for s in retry_symbols]
                for fut in as_completed(futs):
                    pass

            logger.info(f"第 {retry_round} 轮重试完成：剩余失败 {len(failures)}")

        logger.info(f"最终结果：成功 {counters['success']}  跳过 {counters['skipped']}  失败 {len(failures)}")

        fail_log_path = None
        if failures:
            fail_log_path = self._dump_failures(failures, start_date, end_date)
            logger.info(f"最终失败明细: {fail_log_path}")

        return {
            "success": counters["success"],
            "failed": len(failures),
            "skipped": counters["skipped"],
            "fail_log_path": fail_log_path,
            "failures": failures,
        }

    def _fetch_one_incremental(self, symbol: str, ts_start: str, ts_end: str):
        """单股增量拉取。返回 "success" / "skipped" / {failure dict}。"""
        ts_start_ts = pd.to_datetime(ts_start)
        ts_end_ts = pd.to_datetime(ts_end)
        existing_df = self._load_stock_data(symbol)

        ranges = []
        if existing_df.empty:
            ranges.append((ts_start, ts_end))
        else:
            local_min = existing_df[KLineConstants.DATE].min()
            local_max = existing_df[KLineConstants.DATE].max()
            if (local_min - ts_start_ts).days >= 3:
                backfill_end = (local_min - timedelta(days=1)).strftime("%Y%m%d")
                ranges.append((ts_start, backfill_end))
            if (ts_end_ts - local_max).days >= 1:
                forward_start = (local_max + timedelta(days=1)).strftime("%Y%m%d")
                ranges.append((forward_start, ts_end))

        if not ranges:
            return "skipped"

        fetched = False
        empty_ranges: list = []
        for r_start, r_end in ranges:
            df = self._fetch_single_stock(symbol, r_start, r_end)
            if df is not None and not df.empty:
                self._save_stock_data(symbol, df)
                fetched = True
            else:
                empty_ranges.append(f"{r_start}-{r_end}")
            time.sleep(REQUEST_INTERVAL)

        if fetched:
            return "success"
        return {
            "symbol": symbol,
            "reason": "no_data_returned",
            "ranges": empty_ranges,
        }

    @staticmethod
    def _dump_failures(failures: list, start_date: Optional[str],
                       end_date: Optional[str]) -> str:
        """将失败明细写入 output/download_k_fail/{yyyy-mm-dd}.json"""
        import json
        fail_dir = os.path.join(settings.OUTPUT_DIR, "download_k_fail")
        os.makedirs(fail_dir, exist_ok=True)
        fname = (end_date or datetime.now().strftime("%Y-%m-%d")) + ".json"
        path = os.path.join(fail_dir, fname)
        payload = {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "start_date": start_date,
            "end_date": end_date,
            "count": len(failures),
            "failures": failures,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return path

    def _fetch_single_stock(self, symbol: str, start_date: str,
                            end_date: str) -> Optional[pd.DataFrame]:
        """
        获取单只股票日线（前复权）
        :param symbol: 纯数字代码
        :param start_date: YYYYMMDD
        :param end_date: YYYYMMDD
        """
        ts_code = _to_ts_code(symbol)

        for attempt in range(3):
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    df = self.ts.pro_bar(
                        api=self.pro,
                        ts_code=ts_code,
                        adj="qfq",
                        start_date=start_date,
                        end_date=end_date,
                        freq="D",
                    )
            except Exception as e:
                msg = str(e)
                if "每分钟最多访问该接口" in msg or "rate" in msg.lower() or "速度过快" in msg:
                    wait = 2 ** attempt + 1
                    logger.warning(f"{symbol} 触发限流，{wait}s 后重试: {msg}")
                    time.sleep(wait)
                    continue
                logger.debug(f"{symbol} pro_bar 失败: {e}")
                return None

            if df is not None and not df.empty:
                break
            # 返回空可能是限流（代理不报错直接返空），等一下重试
            if attempt < 2:
                time.sleep(1 + attempt)
                continue
            return None
        else:
            return None

        df = df.rename(columns={
            "trade_date": KLineConstants.DATE,
            "open": KLineConstants.OPEN,
            "high": KLineConstants.HIGH,
            "low": KLineConstants.LOW,
            "close": KLineConstants.CLOSE,
            "pre_close": KLineConstants.PRECLOSE,
            "vol": KLineConstants.VOLUME,
            "amount": "amount",
            "pct_chg": "pctChg",
            "change": "change",
        })

        df[KLineConstants.DATE] = pd.to_datetime(df[KLineConstants.DATE], format="%Y%m%d")
        df["code"] = symbol
        df[KLineConstants.STOCK_CODE] = symbol

        df = df.sort_values(KLineConstants.DATE).reset_index(drop=True)
        return df

    def fetch_index(self, ts_code: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """
        获取指数日线数据
        :param ts_code: 指数代码（000001.SH / 399006.SZ / 883957.TI）
        :param start_date: YYYYMMDD
        :param end_date: YYYYMMDD
        """
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                if ts_code.endswith(".TI"):
                    # 同花顺指数
                    df = self.pro.ths_daily(
                        ts_code=ts_code,
                        start_date=start_date,
                        end_date=end_date,
                    )
                else:
                    # 上证 / 深证 指数
                    df = self.ts.pro_bar(
                        api=self.pro,
                        ts_code=ts_code,
                        asset="I",
                        start_date=start_date,
                        end_date=end_date,
                        freq="D",
                    )
        except Exception as e:
            logger.warning(f"指数 {ts_code} 获取失败: {e}")
            return None

        if df is None or df.empty:
            return None

        df = df.rename(columns={
            "trade_date": KLineConstants.DATE,
            "open": KLineConstants.OPEN,
            "high": KLineConstants.HIGH,
            "low": KLineConstants.LOW,
            "close": KLineConstants.CLOSE,
            "pre_close": KLineConstants.PRECLOSE,
            "vol": KLineConstants.VOLUME,
            "amount": "amount",
            "pct_chg": "pctChg",
            "change": "change",
        })

        df[KLineConstants.DATE] = pd.to_datetime(df[KLineConstants.DATE], format="%Y%m%d")
        df["code"] = ts_code
        df[KLineConstants.STOCK_CODE] = ts_code

        df = df.sort_values(KLineConstants.DATE).reset_index(drop=True)
        return df
