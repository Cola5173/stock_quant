"""
Backtest engine wrapper
Based on vnpy BacktestingEngine, provides simplified backtest and optimization interface
"""
import logging
from datetime import datetime
from typing import Type, Optional

from vnpy_ctastrategy.backtesting import BacktestingEngine, OptimizationSetting
from vnpy.trader.constant import Interval

from api.config import settings


class BacktestRunner:
    """Backtest runner"""

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
        self.vt_symbol = vt_symbol

    def run(self) -> dict:
        """Run backtest and return statistics"""
        logger = logging.getLogger("backtest")
        logger.info(f"[{self.vt_symbol}] Loading data: {self.engine.start} ~ {self.engine.end}")

        # Suppress vnpy verbose output
        original_output = self.engine.output
        self.engine.output = lambda msg: None

        self.engine.load_data()
        bar_count = len(self.engine.history_data)
        logger.info(f"[{self.vt_symbol}] Data loaded: {bar_count} bars")

        self.engine.run_backtesting()
        logger.info(f"[{self.vt_symbol}] Backtesting completed")

        self.engine.calculate_result()
        stats = self.engine.calculate_statistics()

        self.engine.output = original_output
        trade_count = stats.get("total_trade_count", 0) or 0
        total_return = stats.get("total_return", 0) or 0
        logger.info(f"[{self.vt_symbol}] Result: return={total_return:.2f}%, trades={trade_count}")
        return stats

    def optimize(self, optimization_setting: OptimizationSetting) -> list:
        """Parameter optimization"""
        return self.engine.run_optimization(optimization_setting)
