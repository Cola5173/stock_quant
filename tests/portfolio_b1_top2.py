"""B1 Top-2 组合回测（v2 高周转版，参考 touzikexue 反推规则）

策略说明:
- 每日扫描全市场，Top-2 评分最高，T+1 开盘等额买入
- 单只仓位 50%
- 大盘（idx_000001_SH）收盘 < 大哥黄 时禁止买入
- 持仓中不再补仓，仅在所有持仓清零后下次扫描重新入场
- 卖出规则（5 类）：
  1. T+3 不涨即卖：持仓 3 个交易日且累计涨幅 < 2% 全清
  2. 跌破长均线（大哥黄）1 日就出
  3. 阴线放量（量比 > 1.5 且跌幅 > 5%）
  4. 上穿短均线（趋势白）后再跌破：曾经站上趋势白后跌破即出
  5. 9 级分批止盈：每涨 +10% 卖剩余仓位 1/3，最高 +90%

用法:
    python tests/portfolio_b1_top2.py --start 2025-01-01 --end 2026-05-17 --workers 8
"""
import argparse
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from glob import glob
from typing import Optional

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.config import settings
from api.schemas.kline_constants import KLineConstants
from api.strategy.b1 import B1Strategy

from tests.scan_v2_style import check_one as scan_check_one, _load_name_map, list_symbols


FEE = settings.FEE_CONFIG
SLIPPAGE = 0.001
INDEX_SYMBOL = "idx_000001_SH"

INDEX_MAP = {
    "60": "idx_000001_SH",
    "00": "idx_399001_SZ",
    "30": "idx_399006_SZ",
    "68": "idx_000016_SH",
}
INDEX_DEFAULT = "idx_000001_SH"


def pick_index_for(symbol: str) -> str:
    """按代码前缀返回对应大盘指数 symbol。
    60→上证, 00→深成, 30→创业, 68→科创(用上证50平替), 其他→上证兜底。
    """
    return INDEX_MAP.get(symbol[:2], INDEX_DEFAULT)


def _load_index_dfs(start_date: str, end_date: str) -> dict:
    """加载所有用到的指数 CSV，校验日期覆盖。
    缺失或日期不覆盖的指数 key 退化到 INDEX_DEFAULT 并打印 warning。
    返回 {idx_symbol: DataFrame}。
    """
    import logging
    logger = logging.getLogger(__name__)
    needed = set(INDEX_MAP.values()) | {INDEX_DEFAULT}
    out = {}
    start = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)
    for idx_sym in needed:
        df = load_csv(idx_sym)
        if df is None or df.empty:
            logger.warning(f"指数 {idx_sym} 缺失，退化到 {INDEX_DEFAULT}")
            out[idx_sym] = None
            continue
        first = df[KLineConstants.DATE].min()
        last = df[KLineConstants.DATE].max()
        if first > start or last < end:
            logger.warning(
                f"指数 {idx_sym} 日期范围 {first.date()}~{last.date()} "
                f"未覆盖回测区间 {start.date()}~{end.date()}，退化到 {INDEX_DEFAULT}"
            )
            out[idx_sym] = None
            continue
        out[idx_sym] = df
    default_df = out.get(INDEX_DEFAULT)
    if default_df is None:
        raise RuntimeError(f"INDEX_DEFAULT={INDEX_DEFAULT} 数据不可用，无法回测")
    return {k: (v if v is not None else default_df) for k, v in out.items()}


T3_HOLD_DAYS = 3
T3_MIN_GAIN_PCT = 2.0
TP_LEVELS = [10, 20, 30, 40, 50, 60, 70, 80, 90]
TP_RATIO = 1.0 / 3.0
BEAR_VOL_RATIO = 1.5
BEAR_DROP_PCT = 5.0
MARKET_BUFFER = 1.00


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


@dataclass
class TradeRecord:
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


def market_allow_buy(date: str, symbol: str, index_dfs: dict) -> bool:
    """大盘收盘 >= 大哥黄 才允许买入（按 symbol 选板块对应指数）。"""
    idx = index_dfs[pick_index_for(symbol)]
    hist = get_history_until(idx, date)
    if hist.empty or len(hist) < 30:
        return False
    closes = hist[KLineConstants.CLOSE].values.astype(float)
    yellow = B1Strategy._yellow_series(closes)
    return float(closes[-1]) >= float(yellow[-1])


def market_is_strong(date: str, symbol: str, index_dfs: dict) -> bool:
    """大盘强势：close >= 大哥黄 且 大哥黄 5 日斜率 > 0（按 symbol 选板块对应指数）。"""
    idx = index_dfs[pick_index_for(symbol)]
    hist = get_history_until(idx, date)
    if hist.empty or len(hist) < 30:
        return False
    closes = hist[KLineConstants.CLOSE].values.astype(float)
    yellow = B1Strategy._yellow_series(closes)
    cond_close = float(closes[-1]) >= float(yellow[-1])
    if len(yellow) >= 6 and float(yellow[-6]) > 0:
        slope_5 = (float(yellow[-1]) / float(yellow[-6])) - 1
    else:
        slope_5 = 0.0
    return cond_close and slope_5 > 0


def calc_sell_signal(pos: Position, df: pd.DataFrame, date: str, market_strong: bool = True):
    """返回 (reason, sell_ratio) 元组"""
    bar = get_bar(df, date)
    if bar is None:
        return None, 0.0
    hist = get_history_until(df, date)
    if len(hist) < 6:
        return None, 0.0

    closes = hist[KLineConstants.CLOSE].values.astype(float)
    volumes = hist[KLineConstants.VOLUME].values.astype(float)
    yellow = B1Strategy._yellow_series(closes)
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

    # 1. 跌破大哥黄 1 日就出
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

    # 5. 分批止盈：每涨 10% 卖剩余仓位的 1/3
    next_lv = pos.tp_level_done + 1
    if next_lv <= len(TP_LEVELS):
        target_gain = TP_LEVELS[next_lv - 1]
        if cur_profit >= target_gain:
            pos.tp_level_done = next_lv
            return f"分批止盈+{target_gain}%(lv{next_lv})", TP_RATIO

    return None, 0.0


def _scan_worker(args):
    symbol, date = args
    return scan_check_one((symbol, date))


def run_backtest(start_date: str, end_date: str, capital: float, workers: int) -> dict:
    name_map = _load_name_map()
    symbols = list_symbols()

    index_dfs = _load_index_dfs(start_date, end_date)
    index_df = index_dfs[INDEX_DEFAULT]  # 用作 trading_days 抽取的参考
    if index_df is None:
        print(f"未找到大盘数据 {INDEX_DEFAULT}.csv，回测中止")
        sys.exit(1)

    trading_days = index_df[
        (index_df[KLineConstants.DATE] >= pd.to_datetime(start_date))
        & (index_df[KLineConstants.DATE] <= pd.to_datetime(end_date))
    ][KLineConstants.DATE].dt.strftime("%Y-%m-%d").tolist()
    if len(trading_days) < 2:
        print("回测区间交易日不足")
        sys.exit(1)

    print(f"回测 {trading_days[0]} ~ {trading_days[-1]}（{len(trading_days)} 个交易日）"
          f" | 初始资金 {capital:,.0f} | 并发 {workers}")

    cash = capital
    positions: dict[str, Position] = {}
    trades: list[TradeRecord] = []
    daily_values: list[dict] = []
    skipped_market_days = 0
    t0 = datetime.now()

    pool = ProcessPoolExecutor(max_workers=workers)

    for i, today in enumerate(trading_days[:-1]):
        next_day = trading_days[i + 1]

        # ===== 1. 检查持仓的卖出信号（T 日数据判断） =====
        sells_today = []  # [(sym, reason, ratio)]
        for sym, pos in list(positions.items()):
            df = load_csv(sym)
            # 持仓股票按自身板块判强弱（决定止损宽紧）
            held_strong = market_is_strong(today, sym, index_dfs)
            reason, ratio = calc_sell_signal(pos, df, today, held_strong)
            if reason:
                sells_today.append((sym, reason, ratio))

        # ===== 2. T+1 开盘卖出（支持分批） =====
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
                buy_date=pos.buy_date, sell_date=next_day,
                symbol=pos.symbol, name=pos.name, shares=sell_shares,
                buy_price=round(pos.cost_price, 2), sell_price=round(sell_price, 2),
                pnl=round(pnl, 2), pnl_pct=round(pnl_pct, 2),
                hold_days=pos.hold_days, sell_reason=reason,
            ))
            pos.shares -= sell_shares
            if pos.shares < 100:
                # 不足 100 股按全清处理
                if pos.shares > 0:
                    cash += pos.shares * sell_price
                del positions[sym]

        # ===== 3. 持仓不满 → 扫描候选补仓（按候选板块判强弱） =====
        if len(positions) < 2:
            tasks = [(s, today) for s in symbols]
            hits = []
            for fut in as_completed({pool.submit(_scan_worker, t): t for t in tasks}):
                r = fut.result()
                if r and r["symbol"] not in positions:
                    # 板块过滤：候选所属板块 close >= 大哥黄 才入池
                    if market_allow_buy(today, r["symbol"], index_dfs):
                        hits.append(r)
            hits.sort(key=lambda x: -x["score"])

            # 按候选板块强弱决定能补几个 slot
            picked = []
            for cand in hits:
                cand_strong = market_is_strong(today, cand["symbol"], index_dfs)
                # 候选板块强：可补到 2 只
                # 候选板块弱：仅在空仓时补 1 只
                if cand_strong:
                    if len(positions) + len(picked) < 2:
                        picked.append(cand)
                else:
                    if len(positions) == 0 and len(picked) == 0:
                        picked.append(cand)
                if len(positions) + len(picked) >= 2:
                    break

            top = picked

            if top:
                per_pos_cap = capital * 0.5
                for cand in top:
                    sym = cand["symbol"]
                    df = load_csv(sym)
                    bar_next = get_bar(df, next_day)
                    if bar_next is None:
                        continue
                    buy_price = float(bar_next[KLineConstants.OPEN]) * (1 + SLIPPAGE)
                    if buy_price <= 0:
                        continue
                    budget = min(per_pos_cap, cash / max(1, len(top)))
                    shares = int(budget / buy_price // 100) * 100
                    if shares <= 0:
                        continue
                    cost = shares * buy_price
                    fee = buy_fee(shares, buy_price)
                    if cash < cost + fee:
                        continue
                    cash -= (cost + fee)
                    bar_today = get_bar(df, today)
                    buy_day_low = float(bar_today[KLineConstants.LOW]) if bar_today is not None else buy_price
                    positions[sym] = Position(
                        symbol=sym,
                        name=name_map.get(sym, sym),
                        shares=shares,
                        cost_price=buy_price,
                        buy_date=next_day,
                        buy_day_low=buy_day_low,
                        initial_shares=shares,
                    )

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
            print(f"  进度 {i+1}/{len(trading_days)-1}  净值 {total:,.0f}  持仓 {len(positions)}  "
                  f"已耗 {el:.0f}s", flush=True)

    pool.shutdown(wait=False)

    # 强制平仓最后一日（按最后一日收盘）
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
            buy_date=pos.buy_date, sell_date=last_day,
            symbol=pos.symbol, name=pos.name, shares=pos.shares,
            buy_price=round(pos.cost_price, 2), sell_price=round(sell_price, 2),
            pnl=round(pnl, 2), pnl_pct=round(pnl_pct, 2),
            hold_days=pos.hold_days, sell_reason="回测结束强平",
        ))
        del positions[sym]

    return aggregate(daily_values, trades, capital, skipped_market_days, trading_days[0], trading_days[-1])


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

    closed = [t for t in trades if t.sell_date and t.pnl_pct is not None]
    wins = [t for t in closed if t.pnl > 0]
    losses = [t for t in closed if t.pnl <= 0]
    win_rate = len(wins) / len(closed) * 100 if closed else 0
    avg_win_pct = float(np.mean([t.pnl_pct for t in wins])) if wins else 0
    avg_loss_pct = float(np.mean([t.pnl_pct for t in losses])) if losses else 0
    best = max(closed, key=lambda t: t.pnl_pct) if closed else None
    worst = min(closed, key=lambda t: t.pnl_pct) if closed else None

    return {
        "period": {"start": start, "end": end, "days": days},
        "stats": {
            "initial_capital": capital,
            "final_value": final,
            "total_return_pct": round(total_return, 2),
            "annual_return_pct": round(annual, 2),
            "max_drawdown_pct": round(max_dd, 2),
            "trades_total": len(trades),
            "trades_closed": len(closed),
            "win_rate_pct": round(win_rate, 2),
            "avg_win_pct": round(avg_win_pct, 2),
            "avg_loss_pct": round(avg_loss_pct, 2),
            "best_trade": {
                "symbol": best.symbol, "name": best.name,
                "pnl_pct": best.pnl_pct, "pnl": best.pnl,
                "buy_date": best.buy_date, "sell_date": best.sell_date,
            } if best else None,
            "worst_trade": {
                "symbol": worst.symbol, "name": worst.name,
                "pnl_pct": worst.pnl_pct, "pnl": worst.pnl,
                "buy_date": worst.buy_date, "sell_date": worst.sell_date,
            } if worst else None,
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
    print(f"B1 Top-2 组合回测结果  {p['start']} ~ {p['end']}（{p['days']} 个交易日）")
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
    print()
    print("=== 交易明细 ===")
    print(f"{'#':<3}{'代码':<8}{'名称':<10}{'买入日':<12}{'卖出日':<12}"
          f"{'股数':>7}{'买价':>8}{'卖价':>8}{'盈亏%':>9}{'持仓':>5}  原因")
    for i, t in enumerate(result["trades"], 1):
        nm = (t["name"] or "")[:8]
        print(f"{i:<3}{t['symbol']:<8}{nm:<10}"
              f"{t['buy_date']:<12}{(t['sell_date'] or '-'):<12}"
              f"{t['shares']:>7}{t['buy_price']:>8.2f}"
              f"{(t['sell_price'] or 0):>8.2f}"
              f"{(t['pnl_pct'] or 0):>+9.2f}{t['hold_days']:>5}  {t['sell_reason']}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2025-01-01")
    parser.add_argument("--end", default=datetime.today().strftime("%Y-%m-%d"))
    parser.add_argument("--capital", type=float, default=1_000_000)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--out", default=None, help="结果保存 json 路径，默认 output/portfolio/b1_top2_<起>_<止>.json")
    args = parser.parse_args()

    result = run_backtest(args.start, args.end, args.capital, args.workers)
    print_report(result)

    out = args.out or os.path.join(
        settings.PORTFOLIO_DIR,
        f"b1_top2_{args.start}_{args.end}.json"
    )
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存: {out}")


if __name__ == "__main__":
    main()
