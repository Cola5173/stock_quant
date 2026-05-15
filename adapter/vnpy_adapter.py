"""
数据适配层
将现有 BaoStock CSV 数据转换为 vnpy BarData 格式并写入 vnpy 数据库
"""
import os
import json
import logging
from datetime import datetime
from typing import Optional

import pandas as pd
from vnpy.trader.constant import Exchange, Interval
from vnpy.trader.object import BarData
from vnpy.trader.database import get_database

from api.config import settings
from api.schemas.kline_constants import KLineConstants
from api.utils.utils import _normalize_stock_code

logger = logging.getLogger(__name__)

EXCHANGE_MAP = {
    "sh": Exchange.SSE,
    "sz": Exchange.SZSE,
}


def _parse_exchange(stock_code: str) -> tuple:
    """
    解析股票代码，返回 (symbol, exchange)
    支持 'sh.600000' 和 '600000' 两种格式
    """
    if "." in stock_code:
        prefix, symbol = stock_code.split(".", 1)
        exchange = EXCHANGE_MAP.get(prefix, Exchange.SSE)
        return symbol, exchange
    if stock_code.startswith("6"):
        return stock_code, Exchange.SSE
    return stock_code, Exchange.SZSE

def _validate_bar(row: pd.Series) -> bool:
    """校验单条 K 线数据的合理性"""
    try:
        h, l, o, c = row["high"], row["low"], row["open"], row["close"]
        if h < l or h < o or h < c or l > o or l > c:
            return False
        if row["volume"] == 0:
            return False
        return True
    except (KeyError, TypeError):
        return False


def _build_extra_info(df: pd.DataFrame, symbol: str) -> dict:
    """提取 A 股特有字段（isST、tradestatus）到映射字典"""
    info = {}
    if KLineConstants.ISST in df.columns:
        last_row = df.iloc[-1]
        info["is_st"] = bool(int(last_row.get(KLineConstants.ISST, 0)))
    return info


class VnpyAdapter:
    """将 BaoStock CSV 数据导入 vnpy 数据库"""

    def __init__(self):
        self.database = get_database()
        self.extra_info_path = os.path.join(settings.DATA_DIR, "stock_extra_info.json")

    def import_single_stock(self, stock_code: str,
                            start_date: Optional[str] = None,
                            end_date: Optional[str] = None) -> int:
        """
        导入单只股票的 CSV 数据到 vnpy 数据库
        :return: 成功导入的 bar 数量
        """
        symbol = _normalize_stock_code(stock_code)
        _, exchange = _parse_exchange(stock_code)
        csv_path = os.path.join(settings.DATA_DIR, f"{symbol}.csv")

        if not os.path.exists(csv_path):
            logger.warning(f"CSV 文件不存在: {csv_path}")
            return 0

        df = pd.read_csv(csv_path)
        if df.empty:
            return 0

        for col in ["open", "high", "low", "close", "volume", "amount"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df["date"] = pd.to_datetime(df["date"])

        if start_date:
            df = df[df["date"] >= pd.to_datetime(start_date)]
        if end_date:
            df = df[df["date"] <= pd.to_datetime(end_date)]

        bars = []
        for _, row in df.iterrows():
            if not _validate_bar(row):
                continue
            bar = BarData(
                symbol=symbol,
                exchange=exchange,
                datetime=row["date"].to_pydatetime(),
                interval=Interval.DAILY,
                open_price=float(row["open"]),
                high_price=float(row["high"]),
                low_price=float(row["low"]),
                close_price=float(row["close"]),
                volume=float(row["volume"]),
                turnover=float(row.get("amount", 0)),
                gateway_name="BaoStock",
            )
            bars.append(bar)

        if bars:
            self.database.save_bar_data(bars)

        self._update_extra_info(symbol, df)
        logger.info(f"导入 {symbol}.{exchange.value}: {len(bars)} 条")
        return len(bars)

    def import_all_stocks(self, start_date: Optional[str] = None,
                          end_date: Optional[str] = None) -> dict:
        """批量导入 data/ 目录下所有 CSV 文件"""
        from tqdm import tqdm

        csv_files = [f for f in os.listdir(settings.DATA_DIR) if f.endswith(".csv")]
        results = {"success": 0, "failed": 0, "total_bars": 0}

        for filename in tqdm(csv_files, desc="导入 vnpy 数据库"):
            symbol = filename.replace(".csv", "")
            try:
                if symbol.startswith("6"):
                    stock_code = f"sh.{symbol}"
                else:
                    stock_code = f"sz.{symbol}"
                count = self.import_single_stock(stock_code, start_date, end_date)
                results["success"] += 1
                results["total_bars"] += count
            except Exception as e:
                logger.error(f"导入 {symbol} 失败: {e}")
                results["failed"] += 1

        return results

    def _update_extra_info(self, symbol: str, df: pd.DataFrame):
        """更新 A 股特有字段映射文件"""
        extra = {}
        if os.path.exists(self.extra_info_path):
            with open(self.extra_info_path, "r") as f:
                extra = json.load(f)

        extra[symbol] = _build_extra_info(df, symbol)

        with open(self.extra_info_path, "w") as f:
            json.dump(extra, f, ensure_ascii=False, indent=2)

