"""V2.1 卖出规则 + 大盘判定（从 tests/portfolio_b1_top2.py 抽离，回测与实盘共用）"""
import os
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from api.config import settings
from api.schemas.kline_constants import KLineConstants

FEE = settings.FEE_CONFIG
SLIPPAGE = 0.001
INDEX_DEFAULT = "idx_000001_SH"

INDEX_MAP = {
    "60": "idx_000001_SH",
    "00": "idx_399001_SZ",
    "30": "idx_399006_SZ",
    "68": "idx_000016_SH",
}

T3_HOLD_DAYS = 3
T3_MIN_GAIN_PCT = 2.0
TP_LEVELS = [10, 20, 30, 40, 50, 60, 70, 80, 90]
TP_RATIO = 1.0 / 3.0
BEAR_VOL_RATIO = 1.5
BEAR_DROP_PCT = 5.0


def _yellow_series(closes: np.ndarray) -> np.ndarray:
    """大哥黄：14/28/57/114 日均线的均值"""
    s = pd.Series(closes)
    return ((s.rolling(14, min_periods=1).mean()
             + s.rolling(28, min_periods=1).mean()
             + s.rolling(57, min_periods=1).mean()
             + s.rolling(114, min_periods=1).mean()) / 4.0).values


def _j_series(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> np.ndarray:
    """KDJ 的 J 值序列"""
    n = 9
    sc = pd.Series(closes)
    sh = pd.Series(highs)
    sl = pd.Series(lows)
    hh = sh.rolling(n, min_periods=1).max()
    ll = sl.rolling(n, min_periods=1).min()
    denom = (hh - ll).replace(0, np.nan)
    rsv = ((sc - ll) / denom * 100).fillna(50).replace([np.inf, -np.inf], 50).values
    k = np.full(len(rsv), 50.0)
    d = np.full(len(rsv), 50.0)
    for i in range(1, len(rsv)):
        k[i] = 2.0 / 3.0 * k[i - 1] + 1.0 / 3.0 * rsv[i]
        d[i] = 2.0 / 3.0 * d[i - 1] + 1.0 / 3.0 * k[i]
    return 3 * k - 2 * d


@dataclass
class Position:
    symbol: str
    name: str
    shares: int
    cost_price: float
    buy_date: str
    buy_day_low: float
    initial_shares: int = 0
    hold_days: int = 0
    max_profit_pct: float = 0.0
    tp_level_done: int = 0
    above_white_once: bool = False


def pick_index_for(symbol: str) -> str:
    return INDEX_MAP.get(symbol[:2], INDEX_DEFAULT)


def buy_fee(shares: int, price: float) -> float:
    amt = shares * price
    return max(amt * FEE["commission_rate"], FEE["min_commission"]) + amt * FEE["transfer_fee_rate"]


def sell_fee(shares: int, price: float) -> float:
    amt = shares * price
    return (max(amt * FEE["commission_rate"], FEE["min_commission"])
            + amt * FEE["stamp_tax_rate"]
            + amt * FEE["transfer_fee_rate"])


def load_csv(symbol: str) -> Optional[pd.DataFrame]:
    path = os.path.join(settings.DATA_DIR, f"{symbol}.csv")
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path)
        for col in [KLineConstants.OPEN, KLineConstants.HIGH, KLineConstants.LOW,
                    KLineConstants.CLOSE, KLineConstants.VOLUME]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df[KLineConstants.DATE] = pd.to_datetime(df[KLineConstants.DATE])
        return df.sort_values(KLineConstants.DATE).reset_index(drop=True)
    except Exception:
        return None


def get_bar(df: pd.DataFrame, date: str) -> Optional[pd.Series]:
    if df is None or df.empty:
        return None
    d = pd.to_datetime(date)
    sub = df[df[KLineConstants.DATE] == d]
    return sub.iloc[0] if not sub.empty else None


def get_history_until(df: pd.DataFrame, date: str) -> pd.DataFrame:
    d = pd.to_datetime(date)
    return df[df[KLineConstants.DATE] <= d].reset_index(drop=True)


def market_allow_buy(date: str, index_df: pd.DataFrame) -> bool:
    """大盘收盘 >= 大哥黄 才允许买入"""
    hist = get_history_until(index_df, date)
    if hist.empty or len(hist) < 30:
        return False
    closes = hist[KLineConstants.CLOSE].values.astype(float)
    yellow = _yellow_series(closes)
    return float(closes[-1]) >= float(yellow[-1])


def market_is_strong(date: str, index_df: pd.DataFrame) -> bool:
    """大盘强势：close >= 大哥黄 且 大哥黄 5 日斜率 > 0"""
    hist = get_history_until(index_df, date)
    if hist.empty or len(hist) < 30:
        return False
    closes = hist[KLineConstants.CLOSE].values.astype(float)
    yellow = _yellow_series(closes)
    cond_close = float(closes[-1]) >= float(yellow[-1])
    if len(yellow) >= 6 and float(yellow[-6]) > 0:
        slope_5 = (float(yellow[-1]) / float(yellow[-6])) - 1
    else:
        slope_5 = 0.0
    return cond_close and slope_5 > 0


def calc_sell_signal(pos: Position, df: pd.DataFrame, date: str,
                     market_strong: bool = True) -> tuple:
    """返回 (reason, sell_ratio)。6 类规则按 0→5 顺序判定，命中即返回。"""
    bar = get_bar(df, date)
    if bar is None:
        return None, 0.0
    hist = get_history_until(df, date)
    if len(hist) < 6:
        return None, 0.0

    closes = hist[KLineConstants.CLOSE].values.astype(float)
    volumes = hist[KLineConstants.VOLUME].values.astype(float)
    yellow = _yellow_series(closes)
    white = pd.Series(closes).ewm(span=10, adjust=False).mean().ewm(span=10, adjust=False).mean().values

    cur_close = float(bar[KLineConstants.CLOSE])
    cur_open = float(bar[KLineConstants.OPEN])
    cur_vol = float(bar[KLineConstants.VOLUME])
    cur_yellow = float(yellow[-1])
    cur_white = float(white[-1])

    pos.hold_days += 1
    cur_profit = (cur_close - pos.cost_price) / pos.cost_price * 100
    pos.max_profit_pct = max(pos.max_profit_pct, cur_profit)

    if cur_close >= cur_white:
        pos.above_white_once = True

    # 0. 硬止损：弱市 -4%，强市 -7%
    stop_pct = -7.0 if market_strong else -4.0
    if cur_profit <= stop_pct:
        return f"硬止损({stop_pct:.0f}%, 当前{cur_profit:.2f}%)", 1.0

    # 1. 跌破大哥黄
    if cur_close < cur_yellow:
        return "跌破大哥黄", 1.0

    # 2. 阴线放量
    vol_ma5 = float(np.mean(volumes[-6:-1])) if len(volumes) >= 6 else 0
    if vol_ma5 > 0 and cur_open > 0:
        vol_r = cur_vol / vol_ma5
        drop_pct = (cur_open - cur_close) / cur_open * 100
        if vol_r > BEAR_VOL_RATIO and drop_pct > BEAR_DROP_PCT:
            return f"阴线放量(量比{vol_r:.1f}/跌{drop_pct:.1f}%)", 1.0

    # 3. 上穿趋势白后再跌破
    if pos.above_white_once and cur_close < cur_white:
        return "破趋势白(曾上穿)", 1.0

    # 4. T+N 不涨即卖
    if pos.hold_days >= T3_HOLD_DAYS and cur_profit < T3_MIN_GAIN_PCT:
        return f"T+{T3_HOLD_DAYS} 涨幅<{T3_MIN_GAIN_PCT}%(当前{cur_profit:+.2f}%)", 1.0

    # 5. 分批止盈
    next_lv = pos.tp_level_done + 1
    if next_lv <= len(TP_LEVELS):
        target_gain = TP_LEVELS[next_lv - 1]
        if cur_profit >= target_gain:
            pos.tp_level_done = next_lv
            return f"分批止盈+{target_gain}%(lv{next_lv})", TP_RATIO

    return None, 0.0
