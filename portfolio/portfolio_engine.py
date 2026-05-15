"""
组合回测引擎
模拟轮动持仓策略，评估整体收益
"""
import json
import logging
import os
from datetime import datetime, timedelta
from typing import List, Optional

import pandas as pd
import numpy as np

from api.config import settings
from indicator.indicators import calculate_KDJ, calculate_zx_trend
from api.schemas.kline_constants import KLineConstants
from utils.utils import _normalize_stock_code

logger = logging.getLogger(__name__)


class PortfolioEngine:
    """组合回测引擎"""

    def __init__(self, initial_capital: float = 100000, max_positions: int = 10,
                 slippage: float = 0.001):
        self.initial_capital = initial_capital
        self.max_positions = max_positions
        self.slippage = slippage
        self.cash = initial_capital
        self.positions = {}   # {symbol: {shares, cost_price, buy_date}}
        self.trades = []
        self.daily_values = []
        self._extra_info = self._load_extra_info()

    def _load_extra_info(self) -> dict:
        path = os.path.join(settings.DATA_DIR, "stock_extra_info.json")
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
        return {}

    def run(self, start_date: str, end_date: str, stock_universe: List[str]) -> dict:
        """
        运行组合回测
        :param start_date: 开始日期 YYYY-MM-DD
        :param end_date: 结束日期 YYYY-MM-DD
        :param stock_universe: 股票池（全市场或子集）
        :return: 统计指标字典
        """
        trading_days = self._get_trading_days(start_date, end_date)
        if not trading_days:
            logger.error("未找到交易日数据")
            return {}

        logger.info(f"组合回测: {start_date} ~ {end_date}, {len(trading_days)} 个交易日")

        for i, date in enumerate(trading_days[:-1]):
            date_str = date.strftime("%Y-%m-%d")
            next_date = trading_days[i + 1]
            next_date_str = next_date.strftime("%Y-%m-%d")

            # T 日收盘后：生成信号
            sell_signals = self._check_sell_signals(date_str, stock_universe)
            buy_candidates = self._scan_buy_candidates(date_str, stock_universe)

            # T+1 日开盘：执行交易
            self._execute_sells(sell_signals, next_date_str)
            self._execute_buys(buy_candidates, next_date_str)

            # 记录 T+1 日净值
            total_value = self._calculate_total_value(next_date_str)
            self.daily_values.append({
                "date": next_date_str,
                "total_value": total_value,
                "cash": self.cash,
                "positions_count": len(self.positions),
            })

        return self._calculate_statistics()

    def _check_sell_signals(self, date: str, stock_universe: List[str]) -> List[str]:
        """检查持仓，生成卖出信号"""
        sell_list = []
        for symbol in list(self.positions.keys()):
            df = self._load_stock_data(symbol, date)
            if df is None or len(df) < 30:
                continue

            try:
                kdj = calculate_KDJ(df)
                if kdj["J"] > 80:
                    sell_list.append(symbol)
            except Exception:
                continue

        return sell_list

    def _scan_buy_candidates(self, date: str, stock_universe: List[str]) -> List[dict]:
        """扫描买入候选"""
        candidates = []
        for stock_code in stock_universe:
            symbol = _normalize_stock_code(stock_code)
            if symbol in self.positions:
                continue

            df = self._load_stock_data(symbol, date)
            if df is None or len(df) < 30:
                continue

            try:
                kdj = calculate_KDJ(df)
                zx = calculate_zx_trend(df)
                close = df[KLineConstants.CLOSE].iloc[-1]

                # B1 策略买入条件
                if (kdj["J"] < 13
                        and zx["zx_trend_white"] > zx["zx_trend_yellow"]
                        and close > zx["zx_trend_yellow"] * 0.99):
                    candidates.append({
                        "symbol": symbol,
                        "close": close,
                        "score": 30 - kdj["J"],  # J 越低分越高
                    })
            except Exception:
                continue

        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates

    def _execute_sells(self, sell_symbols: List[str], date: str):
        """执行卖出"""
        for symbol in sell_symbols:
            if symbol not in self.positions:
                continue

            pos = self.positions[symbol]
            price = self._get_open_price(symbol, date)
            if price is None:
                continue

            # 滑点
            actual_price = price * (1 - self.slippage)
            shares = pos["shares"]
            revenue = shares * actual_price
            fee = self._calculate_sell_fee(shares, actual_price)
            self.cash += revenue - fee

            self.trades.append({
                "date": date,
                "symbol": symbol,
                "action": "sell",
                "price": round(actual_price, 2),
                "shares": shares,
                "fee": round(fee, 2),
                "profit": round(revenue - fee - pos["cost_price"] * shares, 2),
            })

            del self.positions[symbol]

    def _execute_buys(self, candidates: List[dict], date: str):
        """执行买入"""
        available_slots = self.max_positions - len(self.positions)
        if available_slots <= 0:
            return

        position_size = self.initial_capital / self.max_positions

        for candidate in candidates[:available_slots]:
            symbol = candidate["symbol"]
            price = self._get_open_price(symbol, date)
            if price is None:
                continue

            # 滑点
            actual_price = price * (1 + self.slippage)
            shares = int((position_size / actual_price) // 100) * 100
            if shares <= 0:
                continue

            cost = shares * actual_price
            fee = self._calculate_buy_fee(shares, actual_price)
            total_cost = cost + fee

            if self.cash < total_cost:
                continue

            self.cash -= total_cost
            self.positions[symbol] = {
                "shares": shares,
                "cost_price": actual_price,
                "buy_date": date,
            }

            self.trades.append({
                "date": date,
                "symbol": symbol,
                "action": "buy",
                "price": round(actual_price, 2),
                "shares": shares,
                "fee": round(fee, 2),
            })

    def _calculate_buy_fee(self, shares: int, price: float) -> float:
        """买入费用：佣金 + 过户费"""
        amount = shares * price
        commission = max(amount * settings.FEE_CONFIG["commission_rate"],
                         settings.FEE_CONFIG["min_commission"])
        transfer = amount * settings.FEE_CONFIG["transfer_fee_rate"]
        return commission + transfer

    def _calculate_sell_fee(self, shares: int, price: float) -> float:
        """卖出费用：佣金 + 印花税 + 过户费"""
        amount = shares * price
        commission = max(amount * settings.FEE_CONFIG["commission_rate"],
                         settings.FEE_CONFIG["min_commission"])
        stamp_tax = amount * settings.FEE_CONFIG["stamp_tax_rate"]
        transfer = amount * settings.FEE_CONFIG["transfer_fee_rate"]
        return commission + stamp_tax + transfer

    def _calculate_total_value(self, date: str) -> float:
        """计算总资产（现金 + 持仓市值）"""
        total = self.cash
        for symbol, pos in self.positions.items():
            price = self._get_close_price(symbol, date)
            if price:
                total += pos["shares"] * price
            else:
                total += pos["shares"] * pos["cost_price"]
        return round(total, 2)

    def _calculate_statistics(self) -> dict:
        """计算回测统计指标"""
        if not self.daily_values:
            return {}

        values = [v["total_value"] for v in self.daily_values]
        returns = pd.Series(values).pct_change().dropna()

        total_return = (values[-1] - self.initial_capital) / self.initial_capital * 100
        days = len(self.daily_values)
        annual_return = total_return * (252 / days) if days > 0 else 0

        # 最大回撤
        peak = pd.Series(values).cummax()
        drawdown = (pd.Series(values) - peak) / peak * 100
        max_drawdown = drawdown.min()

        # 夏普比率（无风险利率 3%）
        if len(returns) > 1 and returns.std() > 0:
            sharpe = (returns.mean() * 252 - 0.03) / (returns.std() * np.sqrt(252))
        else:
            sharpe = 0

        # 胜率
        winning_trades = [t for t in self.trades if t["action"] == "sell" and t.get("profit", 0) > 0]
        sell_trades = [t for t in self.trades if t["action"] == "sell"]
        win_rate = len(winning_trades) / len(sell_trades) * 100 if sell_trades else 0

        return {
            "period": {
                "start": self.daily_values[0]["date"],
                "end": self.daily_values[-1]["date"],
            },
            "statistics": {
                "initial_capital": self.initial_capital,
                "final_value": values[-1],
                "total_return": round(total_return, 2),
                "annual_return": round(annual_return, 2),
                "max_drawdown": round(max_drawdown, 2),
                "sharpe_ratio": round(sharpe, 2),
                "win_rate": round(win_rate, 2),
                "total_trades": len(self.trades),
            },
            "trades": self.trades,
            "daily_values": self.daily_values,
        }

    # ---- 数据加载辅助方法 ----

    def _load_stock_data(self, symbol: str, date: str) -> Optional[pd.DataFrame]:
        csv_path = os.path.join(settings.DATA_DIR, f"{symbol}.csv")
        if not os.path.exists(csv_path):
            return None
        try:
            df = pd.read_csv(csv_path)
            for col in [KLineConstants.OPEN, KLineConstants.HIGH, KLineConstants.LOW,
                        KLineConstants.CLOSE, KLineConstants.VOLUME]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            df[KLineConstants.DATE] = pd.to_datetime(df[KLineConstants.DATE])
            df = df[df[KLineConstants.DATE] <= pd.to_datetime(date)]
            df = df.sort_values(KLineConstants.DATE).tail(200).reset_index(drop=True)
            return df if not df.empty else None
        except Exception:
            return None

    def _get_open_price(self, symbol: str, date: str) -> Optional[float]:
        csv_path = os.path.join(settings.DATA_DIR, f"{symbol}.csv")
        if not os.path.exists(csv_path):
            return None
        try:
            df = pd.read_csv(csv_path)
            df[KLineConstants.DATE] = pd.to_datetime(df[KLineConstants.DATE])
            df[KLineConstants.OPEN] = pd.to_numeric(df[KLineConstants.OPEN], errors="coerce")
            row = df[df[KLineConstants.DATE] == pd.to_datetime(date)]
            return float(row[KLineConstants.OPEN].iloc[0]) if not row.empty else None
        except Exception:
            return None

    def _get_close_price(self, symbol: str, date: str) -> Optional[float]:
        csv_path = os.path.join(settings.DATA_DIR, f"{symbol}.csv")
        if not os.path.exists(csv_path):
            return None
        try:
            df = pd.read_csv(csv_path)
            df[KLineConstants.DATE] = pd.to_datetime(df[KLineConstants.DATE])
            df[KLineConstants.CLOSE] = pd.to_numeric(df[KLineConstants.CLOSE], errors="coerce")
            row = df[df[KLineConstants.DATE] == pd.to_datetime(date)]
            return float(row[KLineConstants.CLOSE].iloc[0]) if not row.empty else None
        except Exception:
            return None

    def _get_trading_days(self, start_date: str, end_date: str) -> List[datetime]:
        """从参考股票数据中提取交易日列表"""
        ref_csv = os.path.join(settings.DATA_DIR, "000001.csv")
        if not os.path.exists(ref_csv):
            # 尝试其他股票
            for f in os.listdir(settings.DATA_DIR):
                if f.endswith(".csv") and not f.startswith("stock"):
                    ref_csv = os.path.join(settings.DATA_DIR, f)
                    break
        try:
            df = pd.read_csv(ref_csv)
            df[KLineConstants.DATE] = pd.to_datetime(df[KLineConstants.DATE])
            mask = (df[KLineConstants.DATE] >= pd.to_datetime(start_date)) & \
                   (df[KLineConstants.DATE] <= pd.to_datetime(end_date))
            dates = df[mask][KLineConstants.DATE].sort_values().tolist()
            return dates
        except Exception:
            return []
