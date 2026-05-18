"""决策数据结构"""
from dataclasses import dataclass, field


@dataclass
class ActionItem:
    kind: str  # sell / buy / hold / wait
    symbol: str = ""
    name: str = ""
    shares: int = 0
    ratio: float = 0.0
    amount: float = 0.0
    estimated_price: float = 0.0
    estimated_shares: int = 0
    reason: str = ""
    exec_desc: str = ""


@dataclass
class HoldingInfo:
    symbol: str
    name: str
    shares: int
    cost_price: float
    current_close: float
    profit_pct: float
    hold_days: int
    tp_level_done: int
    above_white_once: bool


@dataclass
class Decision:
    date: str
    next_trading_date: str
    market: dict = field(default_factory=dict)
    cooldown: dict = field(default_factory=dict)
    holdings: list = field(default_factory=list)
    actions: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
