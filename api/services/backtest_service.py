"""策略 + 回测服务"""
from datetime import datetime, date, timedelta
from typing import List

from vnpy.trader.constant import Direction

from api.strategy.b1_small import B1SmallStrategy
from api.backtest.engine import BacktestRunner
from api.adapter.vnpy_adapter import VnpyAdapter
from api.schemas.models import (
    StrategyItem, BacktestRequest, BacktestResponse, BacktestStats,
    TradeRecord, EquityPoint,
)


# 策略注册表（key → (name, class, description)）
STRATEGY_REGISTRY = {
    "b1_small": ("B1 Small", B1SmallStrategy, "B1 小资金版：仅主板 + 严格止损 + T+5 时间止损"),
}

# vnpy ArrayManager(size=200) 预热所需的额外历史天数
# load_bar(350) 自然日 ≈ 226 交易日，留余量保证回测开始时 am 已 inited
# 数据库需多导入 ~30 天保证 vnpy 能完整读到 350 天数据
WARMUP_DAYS = 400


def list_strategies() -> List[StrategyItem]:
    return [
        StrategyItem(key=k, name=name, description=desc)
        for k, (name, _, desc) in STRATEGY_REGISTRY.items()
    ]


def _to_vt_symbol(code: str) -> str:
    return f"{code}.SSE" if code.startswith("6") else f"{code}.SZSE"


def run_backtest(req: BacktestRequest) -> BacktestResponse:
    if req.strategy not in STRATEGY_REGISTRY:
        raise ValueError(f"未知策略: {req.strategy}")
    _, strategy_cls, _ = STRATEGY_REGISTRY[req.strategy]

    start_dt = datetime.combine(req.start, datetime.min.time())
    end_dt = datetime.combine(req.end, datetime.min.time())

    # 回测前确保 CSV 数据已导入 vnpy 数据库
    # 向前多导入 WARMUP_DAYS 天数据，供 ArrayManager 预热（否则前 200 根回测 bar
    # 都被用来填 am，期间 execute_logic 不会执行 → 短区间回测早期交易全部丢失）
    import_start = (req.start - timedelta(days=WARMUP_DAYS)).isoformat()
    VnpyAdapter().import_single_stock(req.code, import_start, str(req.end))

    runner = BacktestRunner(
        strategy_class=strategy_cls,
        vt_symbol=_to_vt_symbol(req.code),
        start=start_dt,
        end=end_dt,
        setting={},
    )
    runner.engine.capital = req.capital
    stats = runner.run() or {}

    # 交易明细
    raw_trades = runner.engine.get_all_trades() or []
    strategy = getattr(runner.engine, "strategy", None)
    reasons = list(getattr(strategy, "trade_reasons", []) or [])
    trades: List[TradeRecord] = []
    for t in raw_trades:
        if t.datetime is None:
            continue
        date_str = t.datetime.strftime("%Y-%m-%d")
        direction = "buy" if t.direction == Direction.LONG else "sell"
        reason = ""
        for i, r in enumerate(reasons):
            if r["date"] == date_str and r["direction"] == direction:
                reason = r.get("reason", "")
                reasons.pop(i)
                break
        trades.append(TradeRecord(
            date=date_str,
            direction=direction,
            price=float(t.price),
            volume=int(t.volume),
            reason=reason,
        ))

    # 资金曲线
    equity: List[EquityPoint] = []
    daily_df = getattr(runner.engine, "daily_df", None)
    if daily_df is not None and "balance" in daily_df.columns:
        for idx, balance in zip(daily_df.index, daily_df["balance"]):
            d = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)
            equity.append(EquityPoint(date=d, balance=float(balance)))

    # 交易笔数：一买一卖配对算一笔完整交易
    buy_count = sum(1 for t in trades if t.direction == "buy")
    sell_count = sum(1 for t in trades if t.direction == "sell")
    completed_trades = min(buy_count, sell_count)

    return BacktestResponse(
        stats=BacktestStats(
            total_return=float(stats.get("total_return", 0) or 0),
            max_drawdown=float(stats.get("max_ddpercent", 0) or 0),
            sharpe_ratio=float(stats.get("sharpe_ratio", 0) or 0),
            total_trade_count=completed_trades,
        ),
        trades=trades,
        equity_curve=equity,
    )
