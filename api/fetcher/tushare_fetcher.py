"""
Tushare 数据获取模块
使用 Tushare Pro 接口，通过 config.tushare_client 统一初始化
"""
import os
import io
import time
import logging
import contextlib
from typing import List, Optional
from datetime import datetime, timedelta

import pandas as pd

from .fetcher import DataFetcher
from api.schemas.kline_constants import KLineConstants
from api.config import settings
from .tushare_client import pro, ts
from utils.utils import _normalize_stock_code

logger = logging.getLogger(__name__)

REQUEST_INTERVAL = 0.15


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
              end_date: Optional[str] = None) -> None:
        """批量下载股票日线数据"""
        from tqdm import tqdm

        os.makedirs(settings.DATA_DIR, exist_ok=True)

        print("step 1.1: ----> 获取所有 A 股股票列表...")
        stock_codes = self._get_all_stock_codes()
        if not stock_codes:
            print("未获取到股票列表（请先运行 stock_list 获取，或写入 stock_code.csv）")
            return
        print(f"共 {len(stock_codes)} 只股票")

        ts_start = start_date.replace("-", "") if start_date else "20240101"
        ts_end = end_date.replace("-", "") if end_date else datetime.now().strftime("%Y%m%d")

        print(f"step 1.2: ----> 开始下载 K 线数据 [{start_date} ~ {end_date}]...")
        success_count = 0
        failed_count = 0

        pbar = tqdm(sorted(stock_codes, key=_normalize_stock_code), desc="下载数据")
        for stock_code in pbar:
            try:
                symbol = _normalize_stock_code(stock_code)
                pbar.set_description(f"download {symbol} K line data")

                ts_start_ts = pd.to_datetime(ts_start)
                ts_end_ts = pd.to_datetime(ts_end)
                existing_df = self._load_stock_data(symbol)

                # 计算需要拉取的区间（可能 0~2 段）
                ranges = []
                if existing_df.empty:
                    ranges.append((ts_start, ts_end))
                else:
                    local_min = existing_df[KLineConstants.DATE].min()
                    local_max = existing_df[KLineConstants.DATE].max()
                    # 向前回填 [ts_start, local_min - 1天]：差 >= 3 天才值得请求（避开纯节假日窗口）
                    if (local_min - ts_start_ts).days >= 3:
                        backfill_end = (local_min - timedelta(days=1)).strftime("%Y%m%d")
                        ranges.append((ts_start, backfill_end))
                    # 向后增量 [local_max + 1天, ts_end]：差 >= 1 天即拉
                    if (ts_end_ts - local_max).days >= 1:
                        forward_start = (local_max + timedelta(days=1)).strftime("%Y%m%d")
                        ranges.append((forward_start, ts_end))

                if not ranges:
                    tqdm.write(f"skip {_to_ts_code(symbol)} local data already up to date")
                    continue

                fetched = False
                for r_start, r_end in ranges:
                    df = self._fetch_single_stock(symbol, r_start, r_end)
                    if df is not None and not df.empty:
                        self._save_stock_data(symbol, df)
                        fetched = True
                    time.sleep(REQUEST_INTERVAL)

                if fetched:
                    success_count += 1

            except Exception as e:
                failed_count += 1
                logger.debug(f"下载 {stock_code} 失败: {e}")
                continue

        print(f"step 1.3: ----> 下载完成！")
        print(f"  - 成功: {success_count} 只股票")
        print(f"  - 失败: {failed_count} 只股票")

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
                # tushare 内部对空响应会 print 异常字符串，用 redirect_stdout 静默
                with contextlib.redirect_stdout(io.StringIO()):
                    df = self.ts.pro_bar(
                        api=self.pro,
                        ts_code=ts_code,
                        adj="qfq",
                        start_date=start_date,
                        end_date=end_date,
                        freq="D",
                    )
                break
            except Exception as e:
                msg = str(e)
                if "每分钟最多访问该接口" in msg or "rate" in msg.lower():
                    wait = 2 ** attempt + 1
                    logger.warning(f"{symbol} 触发限流，{wait}s 后重试: {msg}")
                    time.sleep(wait)
                    continue
                logger.debug(f"{symbol} pro_bar 失败: {e}")
                return None
        else:
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
