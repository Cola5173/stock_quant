"""
回测引擎封装
基于 vnpy BacktestingEngine，提供简化的回测和参数优化接口
"""
from datetime import datetime
from typing import Type, Optional

from vnpy_ctastrategy.backtesting import BacktestingEngine, OptimizationSetting
from vnpy.trader.constant import Interval

from config import settings


class BacktestRunner:
    """回测运行器"""

    def __init__(self, strategy_class: Type,
                 vt_symbol: str,
                 start: datetime,
                 end: datetime,
                 setting: Optional[dict] = None):
        cfg = settings.BACKTEST_CONFIG
        self.engine = BacktestingEngine()
        self.engine.set_parameters(
            vt_symbol=vt_symbol,
            interval=Interval.DAILY,
            start=start,
            end=end,
            rate=cfg["rate"],
            slippage=cfg["slippage"],
            size=cfg["size"],
            pricetick=cfg["pricetick"],
            capital=cfg["capital"],
        )
        self.engine.add_strategy(strategy_class, setting or {})

    def run(self) -> dict:
        """运行回测，返回统计指标"""
        self.engine.load_data()
        self.engine.run_backtesting()
        self.engine.calculate_result()
        return self.engine.calculate_statistics()

    def optimize(self, optimization_setting: OptimizationSetting) -> list:
        """参数优化"""
        return self.engine.run_optimization(optimization_setting)
