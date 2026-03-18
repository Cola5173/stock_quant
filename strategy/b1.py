# @Author: cola5173
# @Time: 2025/12/6 21:20

"""
B1策略
选择当日B1的股票
"""
import os
from typing import Optional, Set
from model.kline_constants import KLineConstants
from config import settings
from fetcher.baostock_fetcher import BaoStockDataFetcher
from strategy.base_strategy import BaseStrategy

class B1Strategy(BaseStrategy):
    """
    B1策略：选择当日B1的股票
    专注于选股筛选，不进行评分
    """

    def __init__(self):
        """
        初始化B1策略
        """
        super().__init__()
        self.data_dir = settings.DATA_DIR

    def select(self, trade_date: Optional[str] = None) -> Set[str]:
        return {}

    def select_one(self, stock_code: str, trade_date: Optional[str] = None) -> bool:

        try:
            # trade_date 为空时，使用当前有效交易日
            if trade_date is None:
                trade_date = BaoStockDataFetcher().get_last_trade_date()
                print(f"trade_date 为空，使用当前有效交易日: {trade_date}")
                return False

            # 1. 从data中加载数据
            df = BaoStockDataFetcher().get_stock_data(stock_code)
            if df.empty:
                print(f"股票 {stock_code} 数据为空")
                return False

            # 2. 判断数据是否完整
            if df[KLineConstants.DATE].max() < trade_date:
                print(f"股票 {stock_code} 数据不完整，最新日期: {df[KLineConstants.DATE].max()}, 需要交易日: {trade_date}")
                return False

            # 3. 判断数据是否符合条件
            if df[KLineConstants.CLOSE].iloc[-1] < df[KLineConstants.CLOSE].iloc[-2]:
                print(f"股票 {stock_code} 不符合条件，最新收盘价: {df[KLineConstants.CLOSE].iloc[-1]}, 前一日收盘价: {df[KLineConstants.CLOSE].iloc[-2]}")
                return False

            # 4. 数据完整且符合条件
            # 4.1. KDJ 的 J 值小于 13
            # 4.2. 白线在黄线上方，当日收盘价在黄线的-1%之上，
            # 
            return True 
        except Exception as e:
            print(f"选择股票 {stock_code} 时出错: {e}")
            return False


if __name__ == "__main__":
    strategy = B1Strategy()
    print(strategy.select_one(settings.REFERENCE_STOCK))