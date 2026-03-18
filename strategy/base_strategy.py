# @Author: cola5173
# @Time: 2025/12/7 00:56
"""
策略基类
所有选股策略都需要继承此类并实现 select 方法
"""
from abc import ABC, abstractmethod
from typing import Optional, Set


class BaseStrategy(ABC):
    """策略基类，用于选股"""

    def __init__(self):
        """
        初始化策略
        """

    @abstractmethod
    def select(self,
               trade_date: Optional[str] = None) -> Set[str]:
        """
        批量选股方法，根据指定日期筛选符合条件的股票
        :param trade_date: 选股日期，格式：'YYYY-MM-DD'，如果不传则使用最近的交易日
        :return: 集合，包含符合条件的股票代码，例如 {'000001', '600000'}
        """
        raise NotImplementedError("子类必须实现 select 方法")

    @abstractmethod
    def select_one(self,
                   stock_code: str,
                   trade_date: Optional[str] = None) -> bool:
        """
        单个股票选股方法，根据指定日期筛选符合条件的股票
        :param stock_code: 股票代码，格式：sh.600000 或 sz.000001
        :param trade_date: 选股日期，格式：'YYYY-MM-DD'，如果不传则使用最近的交易日
        :return: 是否符合条件
        """
        raise NotImplementedError("子类必须实现 select_one 方法")
