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
class RiskInfo:
    """持仓风险分析"""
    stop_loss_distance: float = 0.0  # 距离硬止损百分比（正数=安全距离）
    yellow_distance: float = 0.0     # 距离大哥黄百分比（正数=在上方）
    t3_countdown: int = 0            # T+3 倒计时（0=已满3天）
    t3_profit: float = 0.0           # 当前涨幅（T+3 判定用）
    risk_level: str = ""             # low / medium / high
    risk_notes: list = field(default_factory=list)  # 风险提示列表


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
    risk: RiskInfo = field(default_factory=RiskInfo)


@dataclass
class Decision:
    date: str
    next_trading_date: str
    strategy: str = "b1_small"
    market: dict = field(default_factory=dict)
    cooldown: dict = field(default_factory=dict)
    holdings: list = field(default_factory=list)
    actions: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    has_latest_data: bool = False  # 是否有决策日当天的最新数据
