"""统一形态库：关键 K 线识别 + 评分 + 控制力验证。

核心理念：图表中 90%+ K 线无意义，少数关键 K（位置 + 形态 + 量能 三要素）决定走势。
对外只暴露三个入口：
    - score_key_k(df, idx) -> KeyKScore       # 单根 K 评分 + 方向
    - find_key_ks(df, start=None, end=None)   # 区间扫描，返回所有 score≥阈值 的关键 K
    - verify_control(df, idx, lookahead=10)   # 关键 K 的高/低点对后续 N 日的控制力

输入 DataFrame 必须按日期升序，包含列：date / open / high / low / close / volume。
"""
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd

from api.schemas.kline_constants import KLineConstants

# ---------------------------------------------------------------------------
# 阈值（初值，后续可调）
# ---------------------------------------------------------------------------
BIG_BODY_PCT_MAIN = 5.0       # 主板大阳/大阴：实体涨跌 ≥ 5%
BIG_BODY_PCT_GROWTH = 7.0     # 创业/科创：≥ 7%
WINDMILL_RATIO = 2.0          # 影线/实体 ≥ 2
WINDMILL_RANGE_PCT = 5.0      # 总振幅 ≥ 5%
VOL_SURGE_RATIO = 2.0         # 量比 ≥ 2.0
VOL_MA_WINDOW = 20
NEAR_YELLOW_TOL = 1.5         # |close-yellow|/yellow ≤ 1.5%
LOW_PCTL = 30                 # 60 日 close 分位 ≤ 30 视为低位
HIGH_PCTL = 70                # ≥ 70 视为高位
POSITION_LOOKBACK = 60
KEY_K_SCORE_THRESHOLD = 60    # 视为关键 K 的最低分


@dataclass
class KeyKScore:
    idx: int
    date: str
    score: float
    direction: str                 # entry / exit / none
    breakdown: dict = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 底层：单 K 形态（纯函数，输入一个 bar Series 即可）
# ---------------------------------------------------------------------------
def _limit_rate(symbol: Optional[str], is_st: bool = False) -> float:
    """A 股涨跌停幅度。symbol 为 6 位代码字符串，None 时按主板 10% 处理。"""
    if is_st:
        return 0.05
    if symbol and (symbol.startswith("30") or symbol.startswith("68")):
        return 0.20
    return 0.10


def body_pct(bar: pd.Series) -> float:
    """实体涨跌幅 (close-open)/open*100"""
    o = float(bar[KLineConstants.OPEN])
    c = float(bar[KLineConstants.CLOSE])
    if o <= 0:
        return 0.0
    return (c - o) / o * 100


def range_pct(bar: pd.Series) -> float:
    """总振幅 (high-low)/low*100"""
    h = float(bar[KLineConstants.HIGH])
    l = float(bar[KLineConstants.LOW])
    if l <= 0:
        return 0.0
    return (h - l) / l * 100


def is_big_bull(bar: pd.Series, symbol: Optional[str] = None) -> bool:
    threshold = BIG_BODY_PCT_GROWTH if symbol and (symbol.startswith("30") or symbol.startswith("68")) else BIG_BODY_PCT_MAIN
    return body_pct(bar) >= threshold


def is_big_bear(bar: pd.Series, symbol: Optional[str] = None) -> bool:
    threshold = BIG_BODY_PCT_GROWTH if symbol and (symbol.startswith("30") or symbol.startswith("68")) else BIG_BODY_PCT_MAIN
    return body_pct(bar) <= -threshold


def is_windmill(bar: pd.Series) -> bool:
    """大风车：长上下影 + 小实体。影线总长 / |实体| ≥ WINDMILL_RATIO 且总振幅达标。"""
    o = float(bar[KLineConstants.OPEN])
    c = float(bar[KLineConstants.CLOSE])
    h = float(bar[KLineConstants.HIGH])
    l = float(bar[KLineConstants.LOW])
    body = abs(c - o)
    if body <= 0:
        body = max(o, c) * 1e-4  # 极小实体仍按正数处理，避免除零
    upper = h - max(o, c)
    lower = min(o, c) - l
    shadow = upper + lower
    return shadow / body >= WINDMILL_RATIO and range_pct(bar) >= WINDMILL_RANGE_PCT


def is_limit_up(bar: pd.Series, prev_close: float, symbol: Optional[str] = None,
                is_st: bool = False) -> bool:
    if prev_close <= 0:
        return False
    rate = _limit_rate(symbol, is_st)
    pct = (float(bar[KLineConstants.CLOSE]) - prev_close) / prev_close
    return pct >= rate - 0.001


def is_limit_down(bar: pd.Series, prev_close: float, symbol: Optional[str] = None,
                  is_st: bool = False) -> bool:
    if prev_close <= 0:
        return False
    rate = _limit_rate(symbol, is_st)
    pct = (float(bar[KLineConstants.CLOSE]) - prev_close) / prev_close
    return pct <= -rate + 0.001


# ---------------------------------------------------------------------------
# 中层：量能
# ---------------------------------------------------------------------------
def vol_ratio(df: pd.DataFrame, idx: int, ma: int = VOL_MA_WINDOW) -> float:
    """当日成交量 / 前 ma 日均量。前置数据不足返回 0。"""
    if idx < ma:
        return 0.0
    cur = float(df.iloc[idx][KLineConstants.VOLUME])
    prev = df.iloc[idx - ma:idx][KLineConstants.VOLUME].astype(float)
    avg = prev.mean()
    if avg <= 0:
        return 0.0
    return cur / avg


def is_volume_surge(df: pd.DataFrame, idx: int) -> bool:
    return vol_ratio(df, idx) >= VOL_SURGE_RATIO


# ---------------------------------------------------------------------------
# 上层：位置上下文
# ---------------------------------------------------------------------------
def _yellow_at(df: pd.DataFrame, idx: int) -> Optional[float]:
    """大哥黄：(MA14+MA28+MA57+MA114)/4，截至 idx 当日。前置不足返回 None。"""
    if idx < 113:
        return None
    closes = df.iloc[: idx + 1][KLineConstants.CLOSE].astype(float)
    ma1 = closes.rolling(14, min_periods=1).mean().iloc[-1]
    ma2 = closes.rolling(28, min_periods=1).mean().iloc[-1]
    ma3 = closes.rolling(57, min_periods=1).mean().iloc[-1]
    ma4 = closes.rolling(114, min_periods=1).mean().iloc[-1]
    return float((ma1 + ma2 + ma3 + ma4) / 4)


def near_yellow(df: pd.DataFrame, idx: int, tol: float = NEAR_YELLOW_TOL) -> bool:
    y = _yellow_at(df, idx)
    if y is None or y <= 0:
        return False
    c = float(df.iloc[idx][KLineConstants.CLOSE])
    return abs(c - y) / y * 100 <= tol


def position_pct(df: pd.DataFrame, idx: int, lookback: int = POSITION_LOOKBACK) -> float:
    """close 在过去 lookback 日 close 中的分位（0~100）。"""
    start = max(0, idx - lookback + 1)
    window = df.iloc[start: idx + 1][KLineConstants.CLOSE].astype(float).values
    if len(window) < 5:
        return 50.0
    cur = float(window[-1])
    rank = (window <= cur).sum()
    return rank / len(window) * 100


# ---------------------------------------------------------------------------
# 评分入口
# ---------------------------------------------------------------------------
def _form_score(bar: pd.Series, prev_close: float, symbol: Optional[str],
                is_st: bool, intent: str) -> tuple[float, List[str]]:
    """形态分（满分 40）。intent='bull' 看多分支，'bear' 看空分支，'mill' 大风车。"""
    notes: List[str] = []
    score = 0.0

    if intent == "bull":
        if is_big_bull(bar, symbol):
            score += 25
            notes.append(f"大阳线（实体 {body_pct(bar):.1f}%）")
        if is_limit_up(bar, prev_close, symbol, is_st):
            score += 10
            notes.append("涨停板")
    elif intent == "bear":
        if is_big_bear(bar, symbol):
            score += 25
            notes.append(f"大阴线（实体 {body_pct(bar):.1f}%）")
        if is_limit_down(bar, prev_close, symbol, is_st):
            score += 10
            notes.append("跌停板")
        if is_windmill(bar):
            score = max(score, 15)
            notes.append(f"大风车（振幅 {range_pct(bar):.1f}%）")
    elif intent == "mill":
        if is_windmill(bar):
            score += 15
            notes.append(f"大风车（振幅 {range_pct(bar):.1f}%）")

    return min(score, 40.0), notes


def _volume_score(df: pd.DataFrame, idx: int) -> tuple[float, List[str]]:
    """量能分（满分 30）。量比 < 1 得 0，线性映射 (vol_ratio-1)*15，封顶 30。"""
    vr = vol_ratio(df, idx)
    if vr <= 1.0:
        return 0.0, []
    score = min(30.0, (vr - 1) * 15)
    return float(score), [f"放量（量比 {vr:.1f}）"]


def _position_score_entry(df: pd.DataFrame, idx: int) -> tuple[float, List[str]]:
    """入场视角位置分（满分 30）：低位 + 大哥黄附近 各 15。"""
    notes: List[str] = []
    score = 0.0
    pctl = position_pct(df, idx)
    if pctl <= LOW_PCTL:
        score += 15
        notes.append(f"低位（{pctl:.0f} 分位）")
    if near_yellow(df, idx):
        score += 15
        notes.append("大哥黄附近")
    return score, notes


def _position_score_exit(df: pd.DataFrame, idx: int) -> tuple[float, List[str]]:
    """出场视角位置分（满分 30）：高位 + 大哥黄附近 各 15。"""
    notes: List[str] = []
    score = 0.0
    pctl = position_pct(df, idx)
    if pctl >= HIGH_PCTL:
        score += 15
        notes.append(f"高位（{pctl:.0f} 分位）")
    if near_yellow(df, idx):
        score += 15
        notes.append("大哥黄附近")
    return score, notes


def score_key_k(df: pd.DataFrame, idx: int, symbol: Optional[str] = None,
                is_st: bool = False) -> KeyKScore:
    """对 df 第 idx 根 K 打分，返回 KeyKScore。"""
    if idx <= 0 or idx >= len(df):
        return KeyKScore(idx=idx, date=str(df.iloc[idx][KLineConstants.DATE]) if 0 <= idx < len(df) else "",
                         score=0.0, direction="none")

    bar = df.iloc[idx]
    prev_close = float(df.iloc[idx - 1][KLineConstants.CLOSE])
    body = body_pct(bar)

    # 量能 + 大风车都先算，决定后续走 entry / exit / mill
    vol_s, vol_notes = _volume_score(df, idx)
    pctl = position_pct(df, idx)
    windmill = is_windmill(bar)

    # 方向判断：阳 + 量 + (低位 / 大哥黄) → entry；阴 / 跌停 / 高位风车 + 量 → exit
    if body > 0 and vol_s > 0 and (pctl <= LOW_PCTL or near_yellow(df, idx)):
        direction = "entry"
        form_s, form_notes = _form_score(bar, prev_close, symbol, is_st, "bull")
        pos_s, pos_notes = _position_score_entry(df, idx)
    elif (body < 0 or windmill) and vol_s > 0 and (pctl >= HIGH_PCTL or near_yellow(df, idx)):
        direction = "exit"
        intent = "bear" if body < 0 else "mill"
        form_s, form_notes = _form_score(bar, prev_close, symbol, is_st, intent)
        pos_s, pos_notes = _position_score_exit(df, idx)
    else:
        direction = "none"
        # 即使方向不明，也给出形态/量能维度供观察
        intent = "bull" if body > 0 else ("bear" if body < 0 else "mill")
        form_s, form_notes = _form_score(bar, prev_close, symbol, is_st, intent)
        pos_s, pos_notes = (0.0, [])

    total = form_s + vol_s + pos_s
    notes = form_notes + vol_notes + pos_notes

    return KeyKScore(
        idx=idx,
        date=str(df.iloc[idx][KLineConstants.DATE])[:10],
        score=round(total, 2),
        direction=direction,
        breakdown={"form": round(form_s, 2), "volume": round(vol_s, 2), "position": round(pos_s, 2)},
        notes=notes,
    )


def find_key_ks(df: pd.DataFrame, start: Optional[int] = None,
                end: Optional[int] = None, symbol: Optional[str] = None,
                is_st: bool = False, threshold: float = KEY_K_SCORE_THRESHOLD) -> List[KeyKScore]:
    """扫描 [start, end) 区间内所有关键 K（score ≥ threshold）。默认全区间。"""
    if start is None:
        start = max(POSITION_LOOKBACK, 1)
    if end is None:
        end = len(df)
    out = []
    for i in range(start, end):
        s = score_key_k(df, i, symbol=symbol, is_st=is_st)
        if s.score >= threshold and s.direction != "none":
            out.append(s)
    return out


# ---------------------------------------------------------------------------
# 控制力验证
# ---------------------------------------------------------------------------
def verify_control(df: pd.DataFrame, idx: int, lookahead: int = 10,
                   confirm_days: int = 2) -> dict:
    """检查关键 K 的高/低点对后续 lookahead 日的控制力。

    - entry K（看多）：后续 confirm_days 个连续收盘 < 关键 K 低点 → 失效
    - exit K（看空）：后续 confirm_days 个连续收盘 > 关键 K 高点 → 失效

    返回：
        controlled: bool          仍受控
        broken_at: int | None     失效相对索引（首个连续段的最后一日）
        control_score: float      0~100，受控时长 / lookahead × 100
        direction: str            entry / exit
    """
    if idx <= 0 or idx >= len(df):
        return {"controlled": False, "broken_at": None, "control_score": 0.0, "direction": "none"}

    score = score_key_k(df, idx)
    direction = score.direction
    if direction == "none":
        return {"controlled": False, "broken_at": None, "control_score": 0.0, "direction": "none"}

    key_high = float(df.iloc[idx][KLineConstants.HIGH])
    key_low = float(df.iloc[idx][KLineConstants.LOW])
    end = min(len(df), idx + 1 + lookahead)
    closes = df.iloc[idx + 1: end][KLineConstants.CLOSE].astype(float).values
    if len(closes) == 0:
        return {"controlled": True, "broken_at": None, "control_score": 100.0, "direction": direction}

    broken_at: Optional[int] = None
    streak = 0
    for offset, c in enumerate(closes, start=1):
        violated = (direction == "entry" and c < key_low) or (direction == "exit" and c > key_high)
        if violated:
            streak += 1
            if streak >= confirm_days:
                broken_at = offset
                break
        else:
            streak = 0

    controlled_days = (broken_at - confirm_days) if broken_at is not None else len(closes)
    controlled_days = max(0, controlled_days)
    control_score = round(controlled_days / lookahead * 100, 2) if lookahead > 0 else 0.0

    return {
        "controlled": broken_at is None,
        "broken_at": broken_at,
        "control_score": control_score,
        "direction": direction,
    }
