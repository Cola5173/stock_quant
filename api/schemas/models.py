"""Pydantic 请求/响应模型"""
from typing import List, Optional
from datetime import date, datetime
from pydantic import BaseModel, Field


# ====== 股票 ======
class StockItem(BaseModel):
    code: str          # 600000
    name: str          # 浦发银行
    label: str         # 浦发银行 (600000.SH)
    exchange: str      # SH / SZ


# ====== K 线 ======
class KlineBar(BaseModel):
    date: str          # YYYY-MM-DD
    open: float
    high: float
    low: float
    close: float
    volume: float


# ====== 策略 ======
class StrategyItem(BaseModel):
    key: str           # b1
    name: str          # B1 (KDJ+知行趋势)
    description: Optional[str] = None


# ====== 回测 ======
class BacktestRequest(BaseModel):
    strategy: str = Field(..., description="策略 key，如 b1")
    code: str = Field(..., description="股票代码，如 600000")
    start: date
    end: date
    capital: float = Field(100000, ge=10000)


class TradeRecord(BaseModel):
    date: str          # YYYY-MM-DD
    direction: str     # buy / sell
    price: float
    volume: int


class EquityPoint(BaseModel):
    date: str
    balance: float


class BacktestStats(BaseModel):
    total_return: float = 0
    max_drawdown: float = 0
    sharpe_ratio: float = 0
    total_trade_count: int = 0


class BacktestResponse(BaseModel):
    stats: BacktestStats
    trades: List[TradeRecord]
    equity_curve: List[EquityPoint]
