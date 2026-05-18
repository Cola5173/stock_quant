"""派生状态重放：从 buy_date 当天遍历到 today 前一个交易日"""
import pandas as pd

from api.portfolio.rules import Position, calc_sell_signal
from api.schemas.kline_constants import KLineConstants


def replay_state(pos: Position, df: pd.DataFrame, today: str,
                 market_strong: bool = True):
    """从 buy_date（含）到 today（不含）逐 bar 调用 calc_sell_signal 累加状态。
    忽略中间返回的卖出信号——仅用于累加派生字段。
    """
    if df is None or df.empty:
        return
    buy_dt = pd.to_datetime(pos.buy_date)
    today_dt = pd.to_datetime(today)
    dates_in_range = df[
        (df[KLineConstants.DATE] >= buy_dt) &
        (df[KLineConstants.DATE] < today_dt)
    ][KLineConstants.DATE].sort_values().tolist()

    for d in dates_in_range:
        date_str = d.strftime("%Y-%m-%d")
        calc_sell_signal(pos, df, date_str, market_strong)
