"""
数据获取模块基类
用于获取股票数据，支持多种数据源
"""
import os
from typing import Dict, Optional, List, Tuple, Set
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
import pandas as pd
from api.config import settings
from api.schemas.kline_constants import KLineConstants


class DataFetcher(ABC):
    """数据获取器基类"""

    def __init__(self):
        """初始化数据获取器"""
        pass

    def _get_stock_file_path(self, stock_code: str) -> str:
        """
        获取股票数据文件路径（按股票存储方式）
        :param stock_code: 股票代码
        :return: 文件路径
        """
        return os.path.join(settings.DATA_DIR, f"{stock_code}.csv")

    def _load_stock_data(self, stock_code: str,
                         start_date: Optional[str] = None,
                         end_date: Optional[str] = None) -> pd.DataFrame:
        """
        加载股票的历史数据（如果文件存在）
        :param stock_code: 股票代码
        :param start_date: 开始日期，格式：'YYYY-MM-DD'，如果指定则只加载从该日期的数据
        :param end_date: 结束日期，格式：'YYYY-MM-DD'，如果指定则只加载到该日期的数据
        :return: DataFrame，如果文件不存在则返回空DataFrame
        """
        file_path = self._get_stock_file_path(stock_code)
        if os.path.exists(file_path):
            try:
                df = pd.read_csv(file_path)
                if KLineConstants.DATE in df.columns:
                    df[KLineConstants.DATE] = pd.to_datetime(df[KLineConstants.DATE])
                    # 如果指定了结束日期，过滤数据
                    if end_date is not None:
                        end_date_dt = pd.to_datetime(end_date)
                        df = df[df[KLineConstants.DATE] <= end_date_dt]
                    if start_date is not None:
                        start_date_dt = pd.to_datetime(start_date)
                        df = df[df[KLineConstants.DATE] >= start_date_dt]
                    df = df.sort_values(KLineConstants.DATE).reset_index(drop=True)
                return df
            except Exception as e:
                print(f"加载股票 {stock_code} 数据失败: {e}")
                return pd.DataFrame()
        return pd.DataFrame()

    def _save_stock_data(self, stock_code: str, df: pd.DataFrame) -> bool:
        """
        保存股票数据到文件追加方式保存
        :param stock_code: 股票代码
        :param df: 股票数据DataFrame
        :return: 是否保存成功
        """
        try:
            file_path = self._get_stock_file_path(stock_code)

            # 确保数据包含股票代码列
            if KLineConstants.STOCK_CODE not in df.columns:
                df = df.copy()
                df[KLineConstants.STOCK_CODE] = stock_code

            # 加载现有数据（如果存在）
            existing_df = self._load_stock_data(stock_code)

            if not existing_df.empty:
                # 合并数据，去除重复的日期
                combined_df = pd.concat([existing_df, df], ignore_index=True)
                if KLineConstants.DATE in combined_df.columns:
                    # 按日期去重，保留最新的数据
                    combined_df = combined_df.sort_values(KLineConstants.DATE)
                    combined_df = combined_df.drop_duplicates(subset=[KLineConstants.DATE], keep='last')
                    combined_df = combined_df.sort_values(KLineConstants.DATE).reset_index(drop=True)
                else:
                    # 如果没有date列，直接去重
                    combined_df = combined_df.drop_duplicates().reset_index(drop=True)
                df = combined_df
            else:
                # 如果没有现有数据，确保按日期排序
                if KLineConstants.DATE in df.columns:
                    df = df.sort_values(KLineConstants.DATE).reset_index(drop=True)

            # 保存到文件
            df.to_csv(file_path, index=False, encoding='utf-8-sig')
            return True
        except Exception as e:
            print(f"保存股票 {stock_code} 数据失败: {e}")
            return False

    def _get_all_stock_codes(self) -> Set[str]:
        """
        获取所有股票代码列表
        从 stock_code.csv 文件中读取所有股票代码
        :return: 股票代码集合
        """
        stock_codes = set()

        if not os.path.exists(settings.STOCK_CODE_FILE):
            print(f"股票代码文件不存在: {settings.STOCK_CODE_FILE}")
            return stock_codes

        try:
            # 读取CSV文件，没有列名，每行一个股票代码
            with open(settings.STOCK_CODE_FILE, 'r', encoding='utf-8-sig') as f:
                for line in f:
                    code = line.strip()
                    # 跳过空行
                    if code:
                        stock_codes.add(code)
        except Exception as e:
            print(f"读取股票代码文件失败: {e}")

        return stock_codes

    @abstractmethod
    def get_last_trade_date(self) -> str:
        """
        获取实际的最后交易日
        :return: 实际的最后交易日
        """
        raise NotImplementedError("子类需要实现此方法")

    @abstractmethod
    def fetch(self,
              start_date: Optional[str] = None,
              end_date: Optional[str] = None) -> None:
        """
        批量下载股票数据
        :param start_date: 起始日期，格式：'YYYY-MM-DD'，如果不指定则下载最近一个交易日
        :param end_date: 结束日期，格式：'YYYY-MM-DD'，如果不指定则使用start_date（下载单日数据）
        """
        raise NotImplementedError("子类需要实现此方法")
