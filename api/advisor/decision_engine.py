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
from api.advisor.decision_schema import Decision, ActionItem, HoldingInfo, RiskInfo
from api.advisor.position_state import replay_state
from api.advisor.strategy_config import get_config
from api.portfolio.rules import (
    Position, calc_sell_signal, load_csv, get_bar, get_history_until,
    market_allow_buy, market_is_strong, INDEX_DEFAULT,
    _yellow_series, T3_HOLD_DAYS, T3_MIN_GAIN_PCT,
)
from api.schemas.kline_constants import KLineConstants

logger = logging.getLogger(__name__)


def run_decision(date: str, strategy_key: str = "b1_small") -> Decision:
    """主入口：生成指定日期的决策"""
    cfg = get_config(strategy_key)
    positions_data = _load_positions()
    index_df = load_csv(INDEX_DEFAULT)

    market = _market_state(date, index_df, cfg)
    cooldown = _get_cooldown_state(date, index_df)

    holdings_info = []
    actions = []
    warnings = []

    positions = positions_data.get("positions", [])
    total_capital = positions_data.get("total_capital", 100000)

    # 评估持仓
    for p in positions:
        pos, holding, action = _evaluate_one_holding(p, date, market, cfg)
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
                [p["symbol"] for p in positions],
                strategy_key,
                cfg,
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

    # 判断是否有当天最新数据（盘后）
    has_latest_data = False
    if index_df is not None:
        today_bar = get_bar(index_df, date)
        has_latest_data = today_bar is not None

    next_td = _compute_next_trading_date(date)
    decision = Decision(
        date=date,
        strategy=strategy_key,
        next_trading_date=next_td,
        market=market,
        cooldown=cooldown,
        holdings=holdings_info,
        actions=actions,
        warnings=warnings,
        has_latest_data=has_latest_data,
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


def _market_state(date: str, index_df, cfg: dict) -> dict:
    if index_df is None:
        return {"index": INDEX_DEFAULT, "allow_buy": False, "is_strong": False,
                "max_slots": 1, "single_position_pct": 0.40}
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


def _evaluate_one_holding(p: dict, date: str, market: dict, cfg: dict):
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

    # 如果 buy_date > decision_date（今天买入，但决策日对齐到昨天收盘），
    # replay 无 bar 可遍历且 calc_sell_signal 不应执行（那天还没持仓）。
    # 直接报 hold_days=1，无卖出信号。
    buy_dt = pd.to_datetime(p["buy_date"])
    decision_dt = pd.to_datetime(date)
    if buy_dt > decision_dt:
        pos.hold_days = 1
        bar = get_bar(df, date)
        cur_close = float(bar[KLineConstants.CLOSE]) if bar is not None else pos.cost_price
        profit_pct = (cur_close - pos.cost_price) / pos.cost_price * 100
        risk = _compute_risk(pos, df, date, cur_close, profit_pct, market.get("is_strong", True), cfg)
        holding = HoldingInfo(
            symbol=symbol, name=name, shares=pos.shares,
            cost_price=pos.cost_price, current_close=round(cur_close, 2),
            profit_pct=round(profit_pct, 2), hold_days=1,
            tp_level_done=0, above_white_once=False, risk=risk,
        )
        return pos, holding, ActionItem(kind="hold", symbol=symbol, name=name,
                                         reason="买入当天，持仓第 1 天")

    reason, ratio = calc_sell_signal(
        pos, df, date, market.get("is_strong", True),
        hold_days=cfg["hold_days"],
        min_gain_pct=cfg["min_gain_pct"],
        weak_stop_pct=cfg["weak_stop_loss_pct"],
        strong_stop_pct=cfg["strong_stop_loss_pct"],
    )

    bar = get_bar(df, date)
    cur_close = float(bar[KLineConstants.CLOSE]) if bar is not None else pos.cost_price
    profit_pct = (cur_close - pos.cost_price) / pos.cost_price * 100

    # 计算风险信息
    risk = _compute_risk(pos, df, date, cur_close, profit_pct, market.get("is_strong", True), cfg)

    holding = HoldingInfo(
        symbol=symbol, name=name, shares=pos.shares,
        cost_price=pos.cost_price, current_close=round(cur_close, 2),
        profit_pct=round(profit_pct, 2), hold_days=pos.hold_days,
        tp_level_done=pos.tp_level_done, above_white_once=pos.above_white_once,
        risk=risk,
    )

    if reason:
        sell_shares = pos.shares if ratio >= 1.0 else int(pos.shares * ratio // 100) * 100
        action = ActionItem(
            kind="sell", symbol=symbol, name=name,
            shares=sell_shares, ratio=ratio, reason=reason,
            exec_desc="明日开盘市价",
        )
    else:
        hold_reason = _build_hold_reason(risk, profit_pct, pos.hold_days, cfg)
        action = ActionItem(kind="hold", symbol=symbol, name=name,
                            reason=hold_reason)

    return pos, holding, action


def _build_hold_reason(risk: "RiskInfo", profit_pct: float, hold_days: int, cfg: dict) -> str:
    """根据风险信息生成有价值的 hold 提示（明日可能触发的止损/止盈/时间止损）"""
    tips = []

    # 距止损预警
    if risk.stop_loss_distance is not None and risk.stop_loss_distance < 3.0:
        tips.append(f"距硬止损仅 {risk.stop_loss_distance:.1f}%，明日若跌 {risk.stop_loss_distance:.1f}% 将触发止损")

    # 距大哥黄预警
    if risk.yellow_distance is not None and risk.yellow_distance < 2.0:
        tips.append(f"距大哥黄仅 {risk.yellow_distance:.1f}%，跌破将触发卖出")

    # T+N 时间止损预警
    hold_days_cfg = cfg.get("hold_days", 5)
    min_gain_cfg = cfg.get("min_gain_pct", 2.5)
    if risk.t3_countdown is not None:
        if risk.t3_countdown == 0 and profit_pct < min_gain_cfg:
            tips.append(f"T+{hold_days_cfg} 已到期且涨幅 {profit_pct:+.2f}% < {min_gain_cfg}%，明日开盘将卖出")
        elif risk.t3_countdown == 1 and profit_pct < min_gain_cfg:
            tips.append(f"T+{hold_days_cfg} 明日到期，当前涨幅 {profit_pct:+.2f}%（需 ≥ {min_gain_cfg}% 才保留）")

    # 距止盈预警
    tp_levels = [8, 16, 24]
    tp_done = 0
    if hasattr(risk, "t3_profit"):
        pass
    # 简单推算下一档止盈
    for lvl in tp_levels:
        if profit_pct >= lvl:
            tp_done += 1
    if tp_done < len(tp_levels):
        next_tp = tp_levels[tp_done]
        dist_to_tp = next_tp - profit_pct
        if 0 < dist_to_tp < 2.0:
            tips.append(f"距下一档止盈（+{next_tp}%）仅 {dist_to_tp:.1f}%，明日若涨将触发减仓")

    if not tips:
        return "持仓中，暂无风险预警"
    return "；".join(tips)


def _compute_risk(pos: Position, df: pd.DataFrame, date: str,
                  cur_close: float, profit_pct: float, market_strong: bool,
                  cfg: dict) -> RiskInfo:
    """计算持仓风险信息"""
    risk = RiskInfo()
    notes = []

    # 硬止损距离
    stop_pct = -cfg["strong_stop_loss_pct"] if market_strong else -cfg["weak_stop_loss_pct"]
    risk.stop_loss_distance = round(profit_pct - stop_pct, 2)
    if risk.stop_loss_distance < 2.0:
        notes.append(f"距硬止损仅 {risk.stop_loss_distance:.1f}%")

    # 大哥黄距离
    hist = get_history_until(df, date)
    if len(hist) >= 30:
        closes = hist[KLineConstants.CLOSE].values.astype(float)
        yellow = _yellow_series(closes)
        cur_yellow = float(yellow[-1])
        if cur_yellow > 0:
            risk.yellow_distance = round((cur_close / cur_yellow - 1) * 100, 2)
            if risk.yellow_distance < 2.0:
                notes.append(f"距大哥黄仅 {risk.yellow_distance:.1f}%")

    # T+N 倒计时
    hold_days_cfg = cfg["hold_days"]
    min_gain_cfg = cfg["min_gain_pct"]
    risk.t3_countdown = max(0, hold_days_cfg - pos.hold_days)
    risk.t3_profit = round(profit_pct, 2)
    if risk.t3_countdown == 0 and profit_pct < min_gain_cfg:
        notes.append(f"T+{hold_days_cfg} 已到期且涨幅不足 {min_gain_cfg}%（当前 {profit_pct:+.2f}%）")
    elif risk.t3_countdown <= 1 and profit_pct < min_gain_cfg:
        notes.append(f"T+{hold_days_cfg} 倒计时 {risk.t3_countdown} 天，涨幅 {profit_pct:+.2f}% 不足")

    # 趋势白判断
    if pos.above_white_once:
        import numpy as np
        closes_arr = hist[KLineConstants.CLOSE].values.astype(float)
        white = pd.Series(closes_arr).ewm(span=10, adjust=False).mean().ewm(span=10, adjust=False).mean().values
        cur_white = float(white[-1])
        white_dist = (cur_close / cur_white - 1) * 100 if cur_white > 0 else 0
        if white_dist < 1.0:
            notes.append(f"曾上穿趋势白，当前距趋势白仅 {white_dist:.1f}%，跌破即卖")

    # 综合风险等级
    if any("硬止损" in n or "T+3 已到期" in n for n in notes):
        risk.risk_level = "high"
    elif len(notes) >= 2 or any("倒计时" in n or "大哥黄" in n for n in notes):
        risk.risk_level = "medium"
    else:
        risk.risk_level = "low"

    risk.risk_notes = notes
    return risk


def _scan_buy_candidates(date: str, slots_left: int, total_capital: float,
                         position_pct: float, exclude_symbols: list,
                         strategy_key: str, cfg: dict) -> list:
    """复用「策略选股」同一套 Scanner（api/scanner/scanner.py），
    确保「模拟盘明日建议」的候选池 = 策略选股结果，避免两套 scan 逻辑不一致。"""
    from api.scanner.scanner import Scanner

    # 候选池：data/ 下所有 6 位数字 CSV
    stock_codes = sorted(
        f[:-4] for f in os.listdir(settings.DATA_DIR)
        if f.endswith(".csv") and len(f) == 10 and f[:6].isdigit()
    )
    stock_codes = [s for s in stock_codes if s not in exclude_symbols]

    scanner = Scanner(strategy_key, stock_codes)
    hits = scanner.scan(date)
    top = hits[:slots_left]

    actions = []
    for cand in top:
        amount = total_capital * position_pct
        close = cand["close"]
        est_price = close * 1.001
        est_shares = int(amount / est_price // 100) * 100
        if est_shares <= 0:
            continue
        reason = _format_buy_reason(len(actions) + 1, cand)
        actions.append(ActionItem(
            kind="buy",
            symbol=cand["symbol"],
            name=cand.get("name", cand["symbol"]),
            amount=round(amount, 2),
            estimated_price=round(est_price, 2),
            estimated_shares=est_shares,
            reason=reason,
            exec_desc="明日开盘市价（估算价以今日收盘×1.001 计；实际以开盘为准）",
        ))
    return actions


def _format_buy_reason(rank: int, cand: dict) -> str:
    """将 breakdown 列表翻译为可读的中文描述"""
    score = cand.get("score", 0)
    breakdown = cand.get("breakdown", [])

    # 因子名 → 中文描述模板
    factor_map = {
        "红肥": lambda v, s: f"异动后阳线占比{v}" if int(s) > 0 else None,
        "金叉": lambda v, s: "异动前MACD水下金叉" if int(s) > 0 else None,
        "MACD背": lambda v, s: "MACD底背离" if int(s) > 0 else None,
        "J背": lambda v, s: "KDJ J值底背离" if int(s) > 0 else None,
        "量比": lambda v, s: f"异动日量比{v}倍" if int(s) > 0 else None,
        "地量": lambda v, s: "异动后缩量洗盘" if int(s) > 0 else None,
        "快收回": lambda v, s: "跌破黄线后快速收回" if int(s) > 0 else None,
        "破黄": lambda v, s: f"异动后未跌破黄线" if int(s) > 0 else None,
        "跳空": lambda v, s: f"跳空缺口扣{abs(int(s))}分" if int(s) < 0 else None,
        "量价": lambda v, s: f"量价背离扣{abs(int(s))}分" if int(s) < 0 else None,
    }

    highlights = []
    for item in breakdown:
        # 格式: "红肥58%:1" / "MACD背:2 J背:1" / "量比4.5:2"
        parts = item.split()
        for part in parts:
            colon_idx = part.rfind(":")
            if colon_idx < 0:
                continue
            key_val = part[:colon_idx]
            score_str = part[colon_idx + 1:]
            # 提取因子名和数值部分
            matched = False
            for factor_key, fmt_fn in factor_map.items():
                if key_val.startswith(factor_key):
                    val_part = key_val[len(factor_key):]
                    try:
                        desc = fmt_fn(val_part, score_str)
                    except (ValueError, TypeError):
                        desc = None
                    if desc:
                        highlights.append(desc)
                    matched = True
                    break

    detail = "、".join(highlights) if highlights else ""
    header = f"B1异动突破 Top{rank}，评分：{score}"
    if detail:
        return f"{header}，{detail}"
    return header


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


def _serialize_holding(h):
    """序列化 HoldingInfo（嵌套 RiskInfo 也要展开）"""
    if not hasattr(h, '__dict__'):
        return h
    d = vars(h).copy()
    if "risk" in d and hasattr(d["risk"], '__dict__'):
        d["risk"] = vars(d["risk"]).copy()
    return d


def _save_decision(decision: Decision):
    """原子写 decision JSON，并清理掉其它 decision_*.json 旧文件。
    同一决策日重算 → 同名覆盖；决策日变化（如目标交易日更新）→ 旧文件会被一并清掉，
    避免 _load_latest_decision 按文件名排序时取到 stale 数据。
    """
    os.makedirs(settings.DECISIONS_DIR, exist_ok=True)
    date_str = decision.date.replace("-", "")
    path = os.path.join(settings.DECISIONS_DIR, f"decision_{date_str}.json")

    data = {
        "date": decision.date,
        "strategy": decision.strategy,
        "next_trading_date": decision.next_trading_date,
        "market": decision.market,
        "cooldown": decision.cooldown,
        "holdings": [_serialize_holding(h) for h in decision.holdings],
        "actions": [vars(a) if hasattr(a, '__dict__') else a for a in decision.actions],
        "warnings": decision.warnings,
        "has_latest_data": decision.has_latest_data,
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

    # 清理其它 decision_*.json（保留刚写的这一份）
    try:
        from glob import glob as _glob
        for old_path in _glob(os.path.join(settings.DECISIONS_DIR, "decision_*.json")):
            if os.path.abspath(old_path) != os.path.abspath(path):
                try:
                    os.unlink(old_path)
                except OSError as e:
                    logger.debug(f"清理旧决策文件失败 {old_path}: {e}")
    except Exception as e:
        logger.debug(f"清理旧决策文件异常（忽略）: {e}")

    logger.info(f"决策已保存: {path}")
