"""决策引擎：读取持仓 + 大盘状态 + 冷却 → 输出明日动作单"""
import json
import logging
import os
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timedelta

import pandas as pd

from api.config import settings
from api.advisor.cooldown import load_closed_trades, compute_cooldown_state
from api.advisor.decision_schema import Decision, ActionItem, HoldingInfo
from api.advisor.position_state import replay_state
from api.portfolio.rules import (
    Position, calc_sell_signal, load_csv, get_bar, get_history_until,
    market_allow_buy, market_is_strong, INDEX_DEFAULT,
)
from api.schemas.kline_constants import KLineConstants

logger = logging.getLogger(__name__)


def run_decision(date: str) -> Decision:
    """主入口：生成指定日期的决策"""
    positions_data = _load_positions()
    index_df = load_csv(INDEX_DEFAULT)

    market = _market_state(date, index_df)
    cooldown = _get_cooldown_state(date, index_df)

    holdings_info = []
    actions = []
    warnings = []

    positions = positions_data.get("positions", [])
    total_capital = positions_data.get("total_capital", 100000)

    # 评估持仓
    for p in positions:
        pos, holding, action = _evaluate_one_holding(p, date, market)
        if holding:
            holdings_info.append(holding)
        if action:
            actions.append(action)

    # 买入判断
    current_count = len([p for p in positions
                         if not any(a.kind == "sell" and a.symbol == p["symbol"]
                                    and a.ratio >= 1.0 for a in actions)])
    max_slots = market["max_slots"]
    slots_left = max_slots - current_count

    if slots_left > 0:
        if market["allow_buy"] and not cooldown["active"]:
            buy_actions = _scan_buy_candidates(
                date, slots_left, total_capital,
                market["single_position_pct"],
                [p["symbol"] for p in positions]
            )
            actions.extend(buy_actions)
        else:
            reason_parts = []
            if not market["allow_buy"]:
                reason_parts.append("大盘弱：上证收盘 < 大哥黄")
            if cooldown["active"]:
                reason_parts.append(f"连续亏损冷却中，剩余 {cooldown['remaining_days']} 个交易日")
            actions.append(ActionItem(kind="wait", reason="；".join(reason_parts)))

    # 除权除息检测
    for p in positions:
        df = load_csv(p["symbol"])
        if df is not None and len(df) >= 2:
            today_bar = get_bar(df, date)
            if today_bar is not None:
                yesterday = df[df[KLineConstants.DATE] < pd.to_datetime(date)]
                if not yesterday.empty:
                    prev_close = float(yesterday.iloc[-1][KLineConstants.CLOSE])
                    cur_close = float(today_bar[KLineConstants.CLOSE])
                    if prev_close > 0:
                        jump = abs(cur_close - prev_close) / prev_close * 100
                        if jump > 5:
                            warnings.append(
                                f"{p['symbol']} 今日收盘跳变 {jump:.1f}%，请检查除权除息后的 cost_price"
                            )

    next_td = _compute_next_trading_date(date)
    decision = Decision(
        date=date,
        next_trading_date=next_td,
        market=market,
        cooldown=cooldown,
        holdings=holdings_info,
        actions=actions,
        warnings=warnings,
    )

    _save_decision(decision)
    return decision


def _load_positions() -> dict:
    path = settings.POSITIONS_FILE
    if not os.path.exists(path):
        return {"total_capital": 100000, "positions": []}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    for p in data.get("positions", []):
        sym = p.get("symbol", "")
        if not (sym.isdigit() and len(sym) == 6):
            raise ValueError(f"positions.json 校验失败：symbol={sym} 不是 6 位数字")
        if p.get("shares", 0) <= 0:
            raise ValueError(f"positions.json 校验失败：{sym} shares <= 0")
    return data


def _market_state(date: str, index_df) -> dict:
    if index_df is None:
        return {"index": INDEX_DEFAULT, "allow_buy": False, "is_strong": False,
                "max_slots": 1, "single_position_pct": 0.40}
    cfg = settings.ADVISOR_CONFIG
    allow = market_allow_buy(date, index_df)
    strong = market_is_strong(date, index_df)
    max_slots = cfg["max_slots_strong"] if strong else cfg["max_slots_weak"]
    pct = cfg["single_position_pct_strong"] if strong else cfg["single_position_pct_weak"]
    return {
        "index": INDEX_DEFAULT,
        "allow_buy": allow,
        "is_strong": strong,
        "max_slots": max_slots,
        "single_position_pct": pct,
    }


def _get_cooldown_state(date: str, index_df) -> dict:
    if index_df is None:
        return {"active": False, "remaining_days": 0, "cooldown_until": -1}
    trades = load_closed_trades()
    today_dt = pd.to_datetime(date)
    trading_days = index_df[KLineConstants.DATE].sort_values().tolist()
    today_idx = -1
    for i, d in enumerate(trading_days):
        if d >= today_dt:
            today_idx = i
            break
    if today_idx < 0:
        today_idx = len(trading_days)
    return compute_cooldown_state(trades, today_idx)


def _evaluate_one_holding(p: dict, date: str, market: dict):
    """评估单只持仓，返回 (Position, HoldingInfo, ActionItem)"""
    from tests.scan_v2_style import _load_name_map
    name_map = _load_name_map()

    symbol = p["symbol"]
    df = load_csv(symbol)
    name = name_map.get(symbol, symbol)

    pos = Position(
        symbol=symbol, name=name, shares=p["shares"],
        cost_price=p["cost_price"], buy_date=p["buy_date"],
        buy_day_low=p["cost_price"], initial_shares=p["shares"],
    )

    if df is None:
        holding = HoldingInfo(
            symbol=symbol, name=name, shares=p["shares"],
            cost_price=p["cost_price"], current_close=0,
            profit_pct=0, hold_days=0, tp_level_done=0, above_white_once=False,
        )
        return pos, holding, ActionItem(kind="hold", symbol=symbol, name=name,
                                         reason="无行情数据")

    replay_state(pos, df, date, market.get("is_strong", True))
    reason, ratio = calc_sell_signal(pos, df, date, market.get("is_strong", True))

    bar = get_bar(df, date)
    cur_close = float(bar[KLineConstants.CLOSE]) if bar is not None else pos.cost_price
    profit_pct = (cur_close - pos.cost_price) / pos.cost_price * 100

    holding = HoldingInfo(
        symbol=symbol, name=name, shares=pos.shares,
        cost_price=pos.cost_price, current_close=round(cur_close, 2),
        profit_pct=round(profit_pct, 2), hold_days=pos.hold_days,
        tp_level_done=pos.tp_level_done, above_white_once=pos.above_white_once,
    )

    if reason:
        sell_shares = pos.shares if ratio >= 1.0 else int(pos.shares * ratio // 100) * 100
        action = ActionItem(
            kind="sell", symbol=symbol, name=name,
            shares=sell_shares, ratio=ratio, reason=reason,
            exec_desc="明日开盘市价",
        )
    else:
        action = ActionItem(kind="hold", symbol=symbol, name=name,
                            reason="持仓中且无卖出信号")

    return pos, holding, action


def _scan_buy_candidates(date: str, slots_left: int, total_capital: float,
                         position_pct: float, exclude_symbols: list) -> list:
    """调用 scan_v2_style.check_one 并发扫描全市场，取 top"""
    from tests.scan_v2_style import check_one, list_symbols, _load_name_map

    symbols = list_symbols()
    tasks = [(s, date) for s in symbols if s not in exclude_symbols]

    hits = []
    with ProcessPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(check_one, t): t for t in tasks}
        for fut in as_completed(futures):
            r = fut.result()
            if r:
                hits.append(r)

    hits.sort(key=lambda x: -x["score"])
    top = hits[:slots_left]

    actions = []
    for cand in top:
        amount = total_capital * position_pct
        close = cand["close"]
        est_price = close * 1.001
        est_shares = int(amount / est_price // 100) * 100
        if est_shares <= 0:
            continue
        actions.append(ActionItem(
            kind="buy",
            symbol=cand["symbol"],
            name=cand.get("name", cand["symbol"]),
            amount=round(amount, 2),
            estimated_price=round(est_price, 2),
            estimated_shares=est_shares,
            reason=f"V2 ML 评分 Top{len(actions)+1} (score={cand['score']:.1f})",
            exec_desc="明日开盘市价（估算价以今日收盘×1.001 计；实际以开盘为准）",
        ))
    return actions


def _compute_next_trading_date(date: str) -> str:
    """找下一个交易日"""
    d = datetime.strptime(date, "%Y-%m-%d")
    for _ in range(10):
        d += timedelta(days=1)
        try:
            import chinese_calendar
            if chinese_calendar.is_workday(d):
                return d.strftime("%Y-%m-%d")
        except ImportError:
            if d.weekday() < 5:
                return d.strftime("%Y-%m-%d")
    return (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")


def _save_decision(decision: Decision):
    """原子写 decision JSON"""
    os.makedirs(settings.DECISIONS_DIR, exist_ok=True)
    date_str = decision.date.replace("-", "")
    path = os.path.join(settings.DECISIONS_DIR, f"decision_{date_str}.json")

    data = {
        "date": decision.date,
        "next_trading_date": decision.next_trading_date,
        "market": decision.market,
        "cooldown": decision.cooldown,
        "holdings": [vars(h) if hasattr(h, '__dict__') else h for h in decision.holdings],
        "actions": [vars(a) if hasattr(a, '__dict__') else a for a in decision.actions],
        "warnings": decision.warnings,
    }

    tmp_fd, tmp_path = tempfile.mkstemp(dir=settings.DECISIONS_DIR, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    logger.info(f"决策已保存: {path}")
