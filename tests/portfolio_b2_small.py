"""B2 Small 组合回测（小资金 20w 专用）

策略说明:
- 选股：B2 真实选股逻辑（T-1 是 B1 + T 日放量阳确认 + 多门重炮形态）
- 仅主板（600/000/001 开头），价格 ≤ 100 元
- 大盘（idx_000001_SH）收盘 < 大哥黄 时禁止买入
- 强市最多 2 只（单只 50%），弱市最多 1 只（单只 40%）
- 卖出规则与 portfolio_b1_small 一致（B2Small 继承 B1Small 的资金管理）：
  0. 硬止损：弱市 -3%，强市 -5%（小资金严格保护）
  1. 跌破大哥黄 1 日就出
  2. 阴线放量（量比 > 1.5 且跌幅 > 5%）
  3. 上穿趋势白后再跌破即出
  4. T+5 不涨即卖：持仓 5 个交易日且累计涨幅 < 2%
  5. 分批止盈：每涨 +8% 卖剩余仓位 1/3（最高 +24%）
- 连续 2 笔亏损后冷却 10 日
- 同一只票止损后 20 日内不再买入

用法:
    python tests/portfolio_b2_small.py --start 2024-01-01 --end 2026-05-19 --capital 200000 --workers 8
"""
import argparse
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.config import settings
from api.schemas.kline_constants import KLineConstants
from api.portfolio.rules import _yellow_series
from api.strategy.b1_small import B1SmallStrategy

from tests.scan_b2_full import check_one as scan_b2_check_one
from tests.scan_b1_full import _load_name_map, list_symbols


FEE = settings.FEE_CONFIG
SLIPPAGE = 0.001
INDEX_DEFAULT = "idx_000001_SH"
INDEX_MAP = {
    "60": "idx_000001_SH",
    "00": "idx_399001_SZ",
}

# B2 限价单入场参数（"洗盘到攻击性阳线一半位置"）
# 目标价 = B2_open + (B2_close - B2_open) * (1 - ENTRY_TARGET_RATIO)
#   ratio=0.5 → 阳线中点；ratio=0.6 → 更深回踩；ratio=0.4 → 更浅
# 参数扫描最优：ratio=0.4 wait=2（收益 +16.44%，胜率 70.37%，回撤 -6.66%）
ENTRY_TARGET_RATIO = 0.4
ENTRY_WAIT_DAYS = 2      # T+1 起算 N 个交易日内未触发即放弃

# === 小资金参数（与 B1SmallStrategy 对齐）===
MAX_PRICE = B1SmallStrategy.max_price
T5_HOLD_DAYS = B1SmallStrategy.time_stop_days
T5_MIN_GAIN_PCT = B1SmallStrategy.time_stop_min_gain_pct
WEAK_STOP_PCT = -B1SmallStrategy.weak_stop_loss_pct
STRONG_STOP_PCT = -B1SmallStrategy.strong_stop_loss_pct

TP_LEVELS = [8, 16, 24]
TP_RATIO = 1.0 / 3.0
BEAR_VOL_RATIO = 1.5
BEAR_DROP_PCT = 5.0
STOCK_COOLDOWN_DAYS = 20
COOLDOWN_LOSS_STREAK = 2
COOLDOWN_OFFSET = 10


def pick_index_for(symbol: str) -> str:
    return INDEX_MAP.get(symbol[:2], INDEX_DEFAULT)


def is_main_board(symbol: str) -> bool:
    return (symbol.startswith("600")
            or symbol.startswith("000")
            or symbol.startswith("001"))


@dataclass
class Position:
    symbol: str
    name: str
    shares: int
    cost_price: float
    buy_date: str
    buy_day_low: float
    scan_date: str = ""
    initial_shares: int = 0
    hold_days: int = 0
    max_profit_pct: float = 0.0
    tp_level_done: int = 0
    above_white_once: bool = False


@dataclass
class TradeRecord:
    scan_date: str
    buy_date: str
    sell_date: Optional[str]
    symbol: str
    name: str
    shares: int
    buy_price: float
    sell_price: Optional[float]
    pnl: Optional[float]
    pnl_pct: Optional[float]
    hold_days: int
    sell_reason: Optional[str]


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


def _load_index_dfs(start_date: str, end_date: str) -> dict:
    import logging
    logger = logging.getLogger(__name__)
    needed = set(INDEX_MAP.values()) | {INDEX_DEFAULT}
    out = {}
    start = pd.to_datetime(start_date)
    for idx_sym in needed:
        df = load_csv(idx_sym)
        if df is None or df.empty:
            logger.warning(f"指数 {idx_sym} 缺失，退化到 {INDEX_DEFAULT}")
            out[idx_sym] = None
            continue
        first = df[KLineConstants.DATE].min()
        last = df[KLineConstants.DATE].max()
        if first > start or last < start:
            logger.warning(f"指数 {idx_sym} 日期不覆盖，退化到 {INDEX_DEFAULT}")
            out[idx_sym] = None
            continue
        out[idx_sym] = df
    default_df = out.get(INDEX_DEFAULT)
    if default_df is None:
        raise RuntimeError(f"INDEX_DEFAULT={INDEX_DEFAULT} 数据不可用")
    return {k: (v if v is not None else default_df) for k, v in out.items()}


def market_allow_buy(date: str, symbol: str, index_dfs: dict) -> bool:
    idx = index_dfs[pick_index_for(symbol)]
    hist = get_history_until(idx, date)
    if hist.empty or len(hist) < 30:
        return False
    closes = hist[KLineConstants.CLOSE].values.astype(float)
    yellow = _yellow_series(closes)
    return float(closes[-1]) >= float(yellow[-1])


def market_is_strong(date: str, symbol: str, index_dfs: dict) -> bool:
    idx = index_dfs[pick_index_for(symbol)]
    hist = get_history_until(idx, date)
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


def calc_sell_signal(pos: Position, df: pd.DataFrame, date: str, market_strong: bool):
    """返回 (reason, sell_ratio)"""
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

    # 0. 硬止损：弱市 -3%，强市 -5%
    stop_pct = STRONG_STOP_PCT if market_strong else WEAK_STOP_PCT
    if cur_profit <= stop_pct:
        return f"小资金硬止损({stop_pct:.0f}%, 当前{cur_profit:+.2f}%)", 1.0

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

    # 4. T+5 不涨即卖
    if pos.hold_days >= T5_HOLD_DAYS and cur_profit < T5_MIN_GAIN_PCT:
        return f"T+{T5_HOLD_DAYS} 涨幅<{T5_MIN_GAIN_PCT}%(当前{cur_profit:+.2f}%)", 1.0

    # 5. 分批止盈：每涨 8% 卖 1/3
    next_lv = pos.tp_level_done + 1
    if next_lv <= len(TP_LEVELS):
        target_gain = TP_LEVELS[next_lv - 1]
        if cur_profit >= target_gain:
            pos.tp_level_done = next_lv
            return f"分批止盈+{target_gain}%(lv{next_lv})", TP_RATIO

    return None, 0.0


def _scan_worker(args):
    """B2 真实选股 + 小资金过滤（仅主板 + 价格 ≤ 100）"""
    symbol, date = args
    if not is_main_board(symbol):
        return None
    r = scan_b2_check_one((symbol, date))
    if r is None:
        return None
    if r.get("close", 0) > MAX_PRICE:
        return None
    return r


def _load_st_set() -> set:
    path = os.path.join(settings.DATA_DIR, "stock_extra_info.json")
    if not os.path.exists(path):
        return set()
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return {k for k, v in data.items() if v.get("is_st", False)}
    except Exception:
        return set()


def run_backtest(start_date: str, end_date: str, capital: float, workers: int) -> dict:
    name_map = _load_name_map()
    symbols = list_symbols()
    st_set = _load_st_set()
    symbols = [s for s in symbols if is_main_board(s) and s not in st_set]

    index_dfs = _load_index_dfs(start_date, end_date)
    index_df = index_dfs[INDEX_DEFAULT]
    if index_df is None:
        print(f"未找到大盘数据 {INDEX_DEFAULT}.csv")
        sys.exit(1)

    trading_days = index_df[
        (index_df[KLineConstants.DATE] >= pd.to_datetime(start_date))
        & (index_df[KLineConstants.DATE] <= pd.to_datetime(end_date))
    ][KLineConstants.DATE].dt.strftime("%Y-%m-%d").tolist()
    if len(trading_days) < 2:
        print("回测区间交易日不足")
        sys.exit(1)

    print(f"回测 {trading_days[0]} ~ {trading_days[-1]}（{len(trading_days)} 个交易日）"
          f" | 初始资金 {capital:,.0f} | 主板股票 {len(symbols)} 只 | 并发 {workers}")

    cash = capital
    positions: dict[str, Position] = {}
    trades: list[TradeRecord] = []
    daily_values: list[dict] = []
    skipped_market_days = 0
    consecutive_losses = 0
    cooldown_until = -1
    stock_cooldown: dict[str, int] = {}
    # 限价挂单池：key=symbol, value={target_price, expires_at_idx, scan_date, score}
    pending_orders: dict[str, dict] = {}
    t0 = datetime.now()

    pool = ProcessPoolExecutor(max_workers=workers)

    for i, today in enumerate(trading_days[:-1]):
        next_day = trading_days[i + 1]

        market_ok = market_allow_buy(today, INDEX_DEFAULT, index_dfs)
        market_strong = market_is_strong(today, INDEX_DEFAULT, index_dfs)

        # ===== 0. 撮合 pending_orders（次日 next_day 是检查日；
        #         当 next_day 的 low ≤ target ≤ high 时按 target 成交）=====
        per_pos_cap = capital * (0.50 if market_strong else 0.40)
        max_slots_now = 2 if market_strong else 1
        for sym, order in list(pending_orders.items()):
            if i + 1 > order["expires_at_idx"]:
                del pending_orders[sym]
                continue
            if sym in positions:
                del pending_orders[sym]
                continue
            if len(positions) >= max_slots_now:
                continue
            df = load_csv(sym)
            bar_match = get_bar(df, next_day)
            if bar_match is None:
                continue
            low = float(bar_match[KLineConstants.LOW])
            high = float(bar_match[KLineConstants.HIGH])
            target = order["target_price"]
            if not (low <= target <= high):
                continue
            buy_price = target * (1 + SLIPPAGE)
            if buy_price <= 0 or buy_price > MAX_PRICE:
                del pending_orders[sym]
                continue
            slots_left = max_slots_now - len(positions)
            budget = min(per_pos_cap, cash / max(1, slots_left))
            shares = int(budget / buy_price // 100) * 100
            if shares <= 0:
                continue
            cost = shares * buy_price
            fee = buy_fee(shares, buy_price)
            if cash < cost + fee:
                continue
            cash -= (cost + fee)
            bar_scan = get_bar(df, order["scan_date"])
            buy_day_low = float(bar_scan[KLineConstants.LOW]) if bar_scan is not None else buy_price
            positions[sym] = Position(
                symbol=sym,
                name=name_map.get(sym, sym),
                shares=shares,
                cost_price=buy_price,
                buy_date=next_day,
                buy_day_low=buy_day_low,
                scan_date=order["scan_date"],
                initial_shares=shares,
            )
            del pending_orders[sym]

        # ===== 1. 检查持仓的卖出信号 =====
        sells_today = []
        for sym, pos in list(positions.items()):
            df = load_csv(sym)
            reason, ratio = calc_sell_signal(pos, df, today, market_strong)
            if reason:
                sells_today.append((sym, reason, ratio))

        # ===== 2. T+1 开盘卖出 =====
        for sym, reason, ratio in sells_today:
            pos = positions[sym]
            df = load_csv(sym)
            bar_next = get_bar(df, next_day)
            if bar_next is None:
                continue
            sell_price = float(bar_next[KLineConstants.OPEN]) * (1 - SLIPPAGE)
            sell_shares = pos.shares if ratio >= 1.0 else int(pos.shares * ratio // 100) * 100
            if sell_shares <= 0:
                continue
            revenue = sell_shares * sell_price
            fee = sell_fee(sell_shares, sell_price)
            cash += revenue - fee
            pnl = revenue - fee - pos.cost_price * sell_shares
            pnl_pct = (sell_price - pos.cost_price) / pos.cost_price * 100
            trades.append(TradeRecord(
                scan_date=pos.scan_date, buy_date=pos.buy_date, sell_date=next_day,
                symbol=pos.symbol, name=pos.name, shares=sell_shares,
                buy_price=round(pos.cost_price, 2), sell_price=round(sell_price, 2),
                pnl=round(pnl, 2), pnl_pct=round(pnl_pct, 2),
                hold_days=pos.hold_days, sell_reason=reason,
            ))
            pos.shares -= sell_shares
            full_clear = pos.shares < 100
            if full_clear:
                if pos.shares > 0:
                    cash += pos.shares * sell_price
                del positions[sym]
                if pnl_pct < 0:
                    consecutive_losses += 1
                    stock_cooldown[sym] = i + STOCK_COOLDOWN_DAYS
                    if consecutive_losses >= COOLDOWN_LOSS_STREAK:
                        cooldown_until = max(cooldown_until, i + COOLDOWN_OFFSET)
                        consecutive_losses = 0
                else:
                    consecutive_losses = 0

        # ===== 3. B2 选股 → 挂限价单到 B2 阳线中点（不直接 T+1 开盘买）=====
        max_slots = 2 if market_strong else 1
        in_cooldown = i < cooldown_until
        slots = max_slots - len(positions) - len(pending_orders)
        if slots > 0 and market_ok and not in_cooldown:
            tasks = [(s, today) for s in symbols]
            hits = []
            for fut in as_completed({pool.submit(_scan_worker, t): t for t in tasks}):
                r = fut.result()
                if r and r["symbol"] not in positions and r["symbol"] not in pending_orders:
                    sym = r["symbol"]
                    if stock_cooldown.get(sym, -1) > i:
                        continue
                    hits.append(r)
            hits.sort(key=lambda x: -x["score"])
            top = hits[:slots]

            for cand in top:
                sym = cand["symbol"]
                df = load_csv(sym)
                bar_today = get_bar(df, today)
                if bar_today is None:
                    continue
                b2_open = float(bar_today[KLineConstants.OPEN])
                b2_close = float(bar_today[KLineConstants.CLOSE])
                if b2_open <= 0 or b2_close <= b2_open:
                    continue
                # 目标价 = 阳线 (1 - ratio) 处（ratio=0.5 → 中点）
                target_price = b2_open + (b2_close - b2_open) * (1 - ENTRY_TARGET_RATIO)
                pending_orders[sym] = {
                    "target_price": target_price,
                    "expires_at_idx": i + ENTRY_WAIT_DAYS,
                    "scan_date": today,
                    "score": cand["score"],
                }
        elif slots > 0 and not market_ok:
            skipped_market_days += 1

        # ===== 4. 记录次日净值 =====
        total = cash
        for sym, pos in positions.items():
            df = load_csv(sym)
            bar_next = get_bar(df, next_day)
            mark = float(bar_next[KLineConstants.CLOSE]) if bar_next is not None else pos.cost_price
            total += pos.shares * mark
        daily_values.append({"date": next_day, "total": round(total, 2),
                             "cash": round(cash, 2), "positions": len(positions)})

        if (i + 1) % 50 == 0 or i == len(trading_days) - 2:
            el = (datetime.now() - t0).total_seconds()
            print(f"  进度 {i+1}/{len(trading_days)-1}  净值 {total:,.0f}  "
                  f"持仓 {len(positions)}  已耗 {el:.0f}s", flush=True)

    pool.shutdown(wait=False)

    # 强制平仓最后一日
    last_day = trading_days[-1]
    for sym, pos in list(positions.items()):
        df = load_csv(sym)
        bar = get_bar(df, last_day)
        if bar is None:
            continue
        sell_price = float(bar[KLineConstants.CLOSE]) * (1 - SLIPPAGE)
        revenue = pos.shares * sell_price
        fee = sell_fee(pos.shares, sell_price)
        cash += revenue - fee
        pnl = revenue - fee - pos.cost_price * pos.shares
        pnl_pct = (sell_price - pos.cost_price) / pos.cost_price * 100
        trades.append(TradeRecord(
            scan_date=pos.scan_date, buy_date=pos.buy_date, sell_date=last_day,
            symbol=pos.symbol, name=pos.name, shares=pos.shares,
            buy_price=round(pos.cost_price, 2), sell_price=round(sell_price, 2),
            pnl=round(pnl, 2), pnl_pct=round(pnl_pct, 2),
            hold_days=pos.hold_days, sell_reason="回测结束强平",
        ))
        del positions[sym]

    return aggregate(daily_values, trades, capital, skipped_market_days,
                     trading_days[0], trading_days[-1])


def aggregate(daily_values, trades, capital, skipped_days, start, end) -> dict:
    if not daily_values:
        return {}
    final = daily_values[-1]["total"]
    total_return = (final - capital) / capital * 100
    days = len(daily_values)
    annual = total_return * (252 / days) if days > 0 else 0

    totals = pd.Series([v["total"] for v in daily_values])
    peak = totals.cummax()
    dd = (totals - peak) / peak * 100
    max_dd = float(dd.min())

    # 最大回撤区间定位
    dates_arr = [v["date"] for v in daily_values]
    totals_arr = totals.values
    trough_idx = int(dd.values.argmin())
    peak_idx = int(totals_arr[:trough_idx + 1].argmax()) if trough_idx > 0 else 0
    peak_date = dates_arr[peak_idx]
    trough_date = dates_arr[trough_idx]
    peak_value = float(totals_arr[peak_idx])
    trough_value = float(totals_arr[trough_idx])

    # 回撤区间内已平仓交易（按 sell_date 在 [peak_date, trough_date] 范围内）
    period_trades = [
        {
            "scan_date": t.scan_date,
            "buy_date": t.buy_date,
            "sell_date": t.sell_date,
            "symbol": t.symbol,
            "name": t.name,
            "pnl_pct": t.pnl_pct,
            "pnl": t.pnl,
            "sell_reason": t.sell_reason,
        }
        for t in trades
        if t.sell_date and peak_date <= t.sell_date <= trough_date
    ]
    period_pnl = sum(t["pnl"] for t in period_trades if t["pnl"] is not None)
    period_wins = sum(1 for t in period_trades if (t["pnl"] or 0) > 0)
    period_losses = sum(1 for t in period_trades if (t["pnl"] or 0) <= 0)

    closed = [t for t in trades if t.sell_date and t.pnl_pct is not None]
    wins = [t for t in closed if t.pnl > 0]
    losses = [t for t in closed if t.pnl <= 0]
    win_rate = len(wins) / len(closed) * 100 if closed else 0
    avg_win_pct = float(np.mean([t.pnl_pct for t in wins])) if wins else 0
    avg_loss_pct = float(np.mean([t.pnl_pct for t in losses])) if losses else 0

    # 按"持仓"聚合：相同 symbol + buy_date 的多笔分批卖出合并为一笔交易
    # 否则 max(pnl_pct) 会把分批止盈的最后一笔（成本不变但卖价最高）当成最佳
    from collections import defaultdict
    position_groups: dict = defaultdict(list)
    for t in closed:
        position_groups[(t.symbol, t.buy_date)].append(t)
    position_summaries = []
    for (sym, buy_dt), trs in position_groups.items():
        total_cost = sum((tr.buy_price or 0) * (tr.shares or 0) for tr in trs)
        total_revenue = sum((tr.sell_price or 0) * (tr.shares or 0) for tr in trs)
        total_pnl = sum(tr.pnl or 0 for tr in trs)
        pnl_pct = (total_revenue - total_cost) / total_cost * 100 if total_cost > 0 else 0
        last_sell = max((tr.sell_date for tr in trs if tr.sell_date), default=None)
        position_summaries.append({
            "symbol": sym,
            "name": trs[0].name,
            "pnl_pct": round(pnl_pct, 2),
            "pnl": round(total_pnl, 2),
            "buy_date": buy_dt,
            "sell_date": last_sell,
        })
    best = max(position_summaries, key=lambda p: p["pnl_pct"]) if position_summaries else None
    worst = min(position_summaries, key=lambda p: p["pnl_pct"]) if position_summaries else None

    return {
        "period": {"start": start, "end": end, "days": days},
        "stats": {
            "initial_capital": capital,
            "final_value": final,
            "total_return_pct": round(total_return, 2),
            "annual_return_pct": round(annual, 2),
            "max_drawdown_pct": round(max_dd, 2),
            "drawdown_period": {
                "peak_date": peak_date,
                "peak_value": round(peak_value, 2),
                "trough_date": trough_date,
                "trough_value": round(trough_value, 2),
                "duration_days": trough_idx - peak_idx,
                "loss_amount": round(trough_value - peak_value, 2),
                "trades_count": len(period_trades),
                "trades_wins": period_wins,
                "trades_losses": period_losses,
                "trades_pnl": round(period_pnl, 2),
                "trades": period_trades,
            },
            "trades_total": len(trades),
            "trades_closed": len(closed),
            "win_rate_pct": round(win_rate, 2),
            "avg_win_pct": round(avg_win_pct, 2),
            "avg_loss_pct": round(avg_loss_pct, 2),
            "best_trade": best,
            "worst_trade": worst,
            "skipped_market_days": skipped_days,
        },
        "trades": [t.__dict__ for t in trades],
        "daily_values": daily_values,
    }


def print_report(result: dict):
    s = result["stats"]
    p = result["period"]
    print()
    print("=" * 70)
    print(f"B2 Small 组合回测结果  {p['start']} ~ {p['end']}（{p['days']} 个交易日）")
    print("=" * 70)
    print(f"初始资金        : {s['initial_capital']:,.0f}")
    print(f"最终净值        : {s['final_value']:,.0f}")
    print(f"总收益率        : {s['total_return_pct']:+.2f}%")
    print(f"年化收益率      : {s['annual_return_pct']:+.2f}%")
    print(f"最大回撤        : {s['max_drawdown_pct']:.2f}%")
    print(f"交易笔数(已平仓): {s['trades_closed']}")
    print(f"胜率            : {s['win_rate_pct']:.2f}%")
    print(f"平均盈利率      : {s['avg_win_pct']:+.2f}%")
    print(f"平均亏损率      : {s['avg_loss_pct']:+.2f}%")
    if s["best_trade"]:
        b = s["best_trade"]
        print(f"最佳交易        : {b['symbol']} {b['name']}  {b['pnl_pct']:+.2f}%  "
              f"({b['buy_date']} → {b['sell_date']})")
    if s["worst_trade"]:
        w = s["worst_trade"]
        print(f"最差交易        : {w['symbol']} {w['name']}  {w['pnl_pct']:+.2f}%  "
              f"({w['buy_date']} → {w['sell_date']})")
    print(f"大盘禁买跳过日  : {s['skipped_market_days']}")

    # 最大回撤详情
    dp = s.get("drawdown_period")
    if dp:
        print()
        print("=== 最大回撤详情 ===")
        print(f"峰值日          : {dp['peak_date']}  净值 {dp['peak_value']:,.0f}")
        print(f"谷底日          : {dp['trough_date']}  净值 {dp['trough_value']:,.0f}")
        print(f"持续天数        : {dp['duration_days']} 个交易日")
        print(f"亏损金额        : {dp['loss_amount']:+,.0f}")
        print(f"期间交易        : {dp['trades_count']} 笔（盈 {dp['trades_wins']} / 亏 {dp['trades_losses']}）"
              f"  累计 PnL {dp['trades_pnl']:+,.0f}")
        if dp["trades"]:
            print(f"{'代码':<8}{'名称':<10}{'选出':<12}{'买入':<12}{'卖出':<12}{'盈亏%':>9}  原因")
            for t in dp["trades"]:
                nm = (t["name"] or "")[:8]
                print(f"{t['symbol']:<8}{nm:<10}"
                      f"{(t.get('scan_date') or '-'):<12}"
                      f"{t['buy_date']:<12}{(t['sell_date'] or '-'):<12}"
                      f"{(t['pnl_pct'] or 0):>+9.2f}  {t['sell_reason']}")

    print()
    print("=== 交易明细 ===")
    print(f"{'#':<3}{'代码':<8}{'名称':<10}{'选出':<12}{'买入日':<12}{'卖出日':<12}"
          f"{'股数':>7}{'买价':>8}{'卖价':>8}{'盈亏%':>9}{'持仓':>5}  原因")
    for i, t in enumerate(result["trades"], 1):
        nm = (t["name"] or "")[:8]
        print(f"{i:<3}{t['symbol']:<8}{nm:<10}"
              f"{(t.get('scan_date') or '-'):<12}"
              f"{t['buy_date']:<12}{(t['sell_date'] or '-'):<12}"
              f"{t['shares']:>7}{t['buy_price']:>8.2f}"
              f"{(t['sell_price'] or 0):>8.2f}"
              f"{(t['pnl_pct'] or 0):>+9.2f}{t['hold_days']:>5}  {t['sell_reason']}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2025-01-01")
    parser.add_argument("--end", default=datetime.today().strftime("%Y-%m-%d"))
    parser.add_argument("--capital", type=float, default=200_000)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--out", default=None)
    parser.add_argument("--quiet", action="store_true", help="只输出关键统计")
    # 参数扫描专用（可选覆盖）
    parser.add_argument("--weak-stop", type=float, default=None, help="弱市硬止损 %（正数）")
    parser.add_argument("--strong-stop", type=float, default=None, help="强市硬止损 %（正数）")
    parser.add_argument("--t5-days", type=int, default=None, help="T+N 时间止损天数")
    parser.add_argument("--t5-gain", type=float, default=None, help="T+N 最低涨幅 %")
    parser.add_argument("--tp-levels", type=str, default=None, help="止盈档位 逗号分隔，如 8,16,24")
    parser.add_argument("--score-threshold", type=int, default=None, help="B1 打分阈值")
    parser.add_argument("--burst-exhaustion", type=float, default=None, help="burst 耗尽涨幅 %")
    parser.add_argument("--burst-pullback", type=float, default=None, help="burst 耗尽回落 %")
    args = parser.parse_args()

    # 应用参数覆盖
    global WEAK_STOP_PCT, STRONG_STOP_PCT, T5_HOLD_DAYS, T5_MIN_GAIN_PCT, TP_LEVELS
    if args.weak_stop is not None:
        WEAK_STOP_PCT = -args.weak_stop
    if args.strong_stop is not None:
        STRONG_STOP_PCT = -args.strong_stop
    if args.t5_days is not None:
        T5_HOLD_DAYS = args.t5_days
    if args.t5_gain is not None:
        T5_MIN_GAIN_PCT = args.t5_gain
    if args.tp_levels is not None:
        TP_LEVELS = [float(x) for x in args.tp_levels.split(",")]
    if args.score_threshold is not None:
        from api.strategy.b1 import B1Strategy
        B1Strategy.score_threshold = args.score_threshold
    if args.burst_exhaustion is not None:
        from api.strategy.b1 import B1Strategy
        B1Strategy.burst_exhaustion_pct = args.burst_exhaustion
    if args.burst_pullback is not None:
        from api.strategy.b1 import B1Strategy
        B1Strategy.burst_exhaustion_pullback_pct = args.burst_pullback

    result = run_backtest(args.start, args.end, args.capital, args.workers)
    if args.quiet:
        s = result.get("stats", {})
        print(f"RET={s.get('total_return_pct', 0):+.2f}% "
              f"DD={s.get('max_drawdown_pct', 0):.2f}% "
              f"WR={s.get('win_rate_pct', 0):.2f}% "
              f"TRADES={s.get('trades_closed', 0)} "
              f"AVG_WIN={s.get('avg_win_pct', 0):+.2f}% "
              f"AVG_LOSS={s.get('avg_loss_pct', 0):+.2f}%")
    else:
        print_report(result)

    out = args.out or os.path.join(
        settings.PORTFOLIO_DIR,
        f"b2_small_{args.start}_{args.end}.json"
    )
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存: {out}")


if __name__ == "__main__":
    main()
