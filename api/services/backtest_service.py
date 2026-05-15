"""策略 + 回测服务"""
from datetime import datetime, date
from typing import List

from vnpy.trader.constant import Direction

from strategy.b1 import B1Strategy
from backtest.engine import BacktestRunner
from adapter.vnpy_adapter import VnpyAdapter
from api.schemas.models import (
    StrategyItem, BacktestRequest, BacktestResponse, BacktestStats,
    TradeRecord, EquityPoint,
)


# 策略注册表（key → (name, class, description)）
STRATEGY_REGISTRY = {
    "b1": ("B1 (KDJ+知行趋势)", B1Strategy, "基于 KDJ 指标和知行趋势线的择时策略"),
}


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
    VnpyAdapter().import_single_stock(req.code, str(req.start), str(req.end))

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
    trades: List[TradeRecord] = []
    for t in raw_trades:
        if t.datetime is None:
            continue
        trades.append(TradeRecord(
            date=t.datetime.strftime("%Y-%m-%d"),
            direction="buy" if t.direction == Direction.LONG else "sell",
            price=float(t.price),
            volume=int(t.volume),
        ))

    # 资金曲线
    equity: List[EquityPoint] = []
    daily_df = getattr(runner.engine, "daily_df", None)
    if daily_df is not None and "balance" in daily_df.columns:
        for idx, balance in zip(daily_df.index, daily_df["balance"]):
            d = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)
            equity.append(EquityPoint(date=d, balance=float(balance)))

    return BacktestResponse(
        stats=BacktestStats(
            total_return=float(stats.get("total_return", 0) or 0),
            max_drawdown=float(stats.get("max_drawdown", 0) or 0),
            sharpe_ratio=float(stats.get("sharpe_ratio", 0) or 0),
            total_trade_count=int(stats.get("total_trade_count", 0) or 0),
        ),
        trades=trades,
        equity_curve=equity,
    )
