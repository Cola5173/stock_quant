"""
AkShare 数据获取模块
使用 AkShare 数据源获取股票数据（免费，基于东方财富）
"""
import os
import time
import logging
from typing import List, Optional, Set
from datetime import datetime

import pandas as pd

from .fetcher import DataFetcher
from model.kline_constants import KLineConstants
from config import settings
from utils.utils import _normalize_stock_code

logger = logging.getLogger(__name__)

# 请求间隔（秒），避免被东方财富限流
REQUEST_INTERVAL = 0.3


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
            # 通过获取上证指数最近数据来判断最近交易日
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
                from datetime import timedelta
                test_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y%m%d')
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
        批量下载股票数据
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

        print(f"step 1.2: ----> 开始下载K线数据 [{start_date} ~ {end_date}]...")
        failed_count = 0
        success_count = 0

        pbar = tqdm(sorted(stock_codes, key=_normalize_stock_code), desc="下载数据")
        for stock_code in pbar:
            try:
                symbol = _normalize_stock_code(stock_code)
                pbar.set_description(f"download {symbol} K line data")

                # 检查是否需要增量更新
                existing_df = self._load_stock_data(symbol)
                if not existing_df.empty:
                    max_date = existing_df[KLineConstants.DATE].max()
                    ak_end_ts = pd.to_datetime(ak_end)
                    if max_date >= ak_end_ts:
                        continue
                    # 增量下载
                    from datetime import timedelta
                    incremental_start = (max_date + timedelta(days=1)).strftime('%Y%m%d')
                    df = self._fetch_single_stock(symbol, incremental_start, ak_end)
                else:
                    df = self._fetch_single_stock(symbol, ak_start, ak_end)

                if df is not None and not df.empty:
                    self._save_stock_data(symbol, df)
                    success_count += 1

                time.sleep(REQUEST_INTERVAL)

            except Exception as e:
                failed_count += 1
                logger.debug(f"下载 {stock_code} 失败: {e}")
                continue

        print(f"step 1.3: ----> 下载完成！")
        print(f"  - 成功: {success_count} 只股票")
        print(f"  - 失败: {failed_count} 只股票")

    def _fetch_single_stock(self, symbol: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """
        获取单只股票的日线数据
        :param symbol: 纯数字代码（如 600000）
        :param start_date: YYYYMMDD
        :param end_date: YYYYMMDD
        """
        try:
            df = self.ak.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust="qfq"  # 前复权
            )

            if df is None or df.empty:
                return None

            # AkShare 返回的列名是中文，需要转换
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

            # 添加必要字段
            df[KLineConstants.DATE] = pd.to_datetime(df[KLineConstants.DATE])
            df["code"] = symbol
            df["stock_code"] = symbol

            # 计算前收盘价
            if "preclose" not in df.columns:
                df["preclose"] = df[KLineConstants.CLOSE].shift(1)

            df = df.sort_values(KLineConstants.DATE).reset_index(drop=True)
            return df

        except Exception as e:
            logger.debug(f"获取 {symbol} 数据失败: {e}")
            return None

    def _fetch_spot_em_with_retry(self, max_retries: int = 3) -> Optional[pd.DataFrame]:
        """
        调用 ak.stock_zh_a_spot_em() 获取全市场实时行情，带指数退避重试。
        东方财富接口偶发限流/连接被重置，单次失败不代表真的拿不到。
        """
        import requests

        last_err = None
        for attempt in range(max_retries):
            try:
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
