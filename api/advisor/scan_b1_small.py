"""B1 Small 独立扫描器：异动突破 + 多因子打分 + 主板/价格过滤

从 api/strategy/b1.py 提取核心选股逻辑，不依赖 vnpy ArrayManager。
用于模拟盘决策引擎的买入候选扫描。
"""
import os
from typing import Optional

import numpy as np
import pandas as pd

from api.config import settings
from api.schemas.kline_constants import KLineConstants

# B1 策略参数（与 api/strategy/b1.py 保持一致）
KDJ_J_THRESHOLD = 15
BURST_LOOKBACK_DAYS = 50
BURST_MIN_CHG = 2.5
BURST_MAX_CHG = 13.0
BURST_VOL_RATIO = 1.3
BURST_RECENT_BELOW_DAYS = 5
STABLE_DROP_PCT = 5.0
STABLE_DROP_VOL_RATIO = 1.5
DOUBLED_LOOKBACK = 60
DOUBLED_RATIO = 1.8
SCORE_THRESHOLD = 5
MACD_CROSS_LOOKBACK = 60
DIVERGENCE_PRICE_MAX = 25.0
DIVERGENCE_MIN_GAP_DAYS = 5
RED_WINDOW_SIZE = 21

# B1 Small 过滤
MAX_PRICE = 100.0

_NAME_MAP: dict | None = None


def _load_name_map() -> dict:
    global _NAME_MAP
    if _NAME_MAP is not None:
        return _NAME_MAP
    path = os.path.join(settings.DATA_DIR, "stock_names.json")
    if os.path.exists(path):
        import json
        with open(path, "r", encoding="utf-8") as f:
            _NAME_MAP = json.load(f)
    else:
        _NAME_MAP = {}
    return _NAME_MAP
# PLACEHOLDER_FUNCTIONS


def list_symbols() -> list:
    """列出 data/ 下所有 6 位数字 CSV（排除 idx_ 前缀）"""
    files = os.listdir(settings.DATA_DIR)
    return sorted(
        f[:-4] for f in files
        if f.endswith(".csv") and len(f) == 10 and f[:6].isdigit()
    )


def _is_main_board(symbol: str) -> bool:
    return symbol.startswith("600") or symbol.startswith("000") or symbol.startswith("001")


def _yellow_series(closes: np.ndarray) -> np.ndarray:
    s = pd.Series(closes)
    return ((s.rolling(14, min_periods=1).mean()
             + s.rolling(28, min_periods=1).mean()
             + s.rolling(57, min_periods=1).mean()
             + s.rolling(114, min_periods=1).mean()) / 4.0).values


def _white_series(closes: np.ndarray) -> np.ndarray:
    s = pd.Series(closes)
    return s.ewm(span=10, adjust=False).mean().ewm(span=10, adjust=False).mean().values


def _macd_series(closes: np.ndarray) -> tuple:
    s = pd.Series(closes)
    ema12 = s.ewm(span=12, adjust=False).mean()
    ema26 = s.ewm(span=26, adjust=False).mean()
    dif = (ema12 - ema26).values
    dea = pd.Series(dif).ewm(span=9, adjust=False).mean().values
    return dif, dea


def _j_series(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> np.ndarray:
    n = 9
    sc, sh, sl = pd.Series(closes), pd.Series(highs), pd.Series(lows)
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


def _prev_vol_ratio(volumes: np.ndarray, i: int, window: int = 5) -> float:
    if i < window:
        return 0.0
    base = float(np.mean(volumes[i - window:i]))
    return volumes[i] / base if base > 0 else 0.0
# PLACEHOLDER_SCORE


def _compute_score(burst_idx: int, closes, opens, volumes, highs, lows,
                   yellow_arr, dif_arr, dea_arr, j_arr, n_total) -> tuple:
    """多因子打分 A-J，返回 (score, breakdown_list)"""
    score = 0
    breakdown = []

    # A 红肥绿瘦
    win_start = burst_idx
    win_end = min(n_total - 1, burst_idx + RED_WINDOW_SIZE)
    win_closes = closes[win_start:win_end]
    win_opens = opens[win_start:win_end]
    red_pct = 0.0
    red_score = 0
    if len(win_closes) >= 5:
        chg_pct = np.where(win_opens > 0, (win_closes - win_opens) / win_opens * 100, 0.0)
        red_amp = float(np.sum(chg_pct[chg_pct > 0]))
        green_amp = float(-np.sum(chg_pct[chg_pct < 0]))
        total_amp = red_amp + green_amp
        if total_amp > 0:
            red_pct = red_amp / total_amp * 100
            if red_pct >= 70: red_score = 3
            elif red_pct >= 60: red_score = 2
            elif red_pct >= 50: red_score = 1
    score += red_score
    breakdown.append(f"红肥{red_pct:.0f}%:{red_score}")

    # B 水下金叉
    cross_start = max(1, burst_idx - MACD_CROSS_LOOKBACK)
    has_cross = False
    for i in range(cross_start, burst_idx + 1):
        if (dif_arr[i - 1] <= dea_arr[i - 1]
                and dif_arr[i] > dea_arr[i]
                and dif_arr[i] < 0):
            has_cross = True
            break
    b_score = 1 if has_cross else 0
    score += b_score
    breakdown.append(f"金叉:{b_score}")

    # C/D 底背离
    j_lows = []
    scan_start = max(2, burst_idx - 150)
    for i in range(scan_start, burst_idx):
        if j_arr[i] < 0 and j_arr[i] < j_arr[i - 1] and j_arr[i] < j_arr[i + 1]:
            macd_val = (dif_arr[i] - dea_arr[i]) * 2.0
            j_lows.append((i, closes[i], macd_val, j_arr[i]))
    c_score = 0
    d_score = 0
    if len(j_lows) >= 2:
        idx2, p2_price, p2_macd, p2_j = j_lows[-1]
        gap = max(1, DIVERGENCE_MIN_GAP_DAYS)
        prior = [pt for pt in j_lows[:-1] if idx2 - pt[0] >= gap]
        if prior:
            p1 = min(prior, key=lambda x: x[3])
            if p1[1] > 0:
                price_diff = abs(p2_price - p1[1]) / p1[1] * 100
                if price_diff <= DIVERGENCE_PRICE_MAX:
                    if p2_macd >= p1[2]: c_score = 2
                    if p2_j > p1[3]: d_score = 1
    score += c_score + d_score
    breakdown.append(f"MACD背:{c_score} J背:{d_score}")

    # E 异动量比强度
    burst_vr = _prev_vol_ratio(volumes, burst_idx)
    if burst_vr >= 3.0: e_score = 2
    elif burst_vr >= 2.0: e_score = 1
    else: e_score = 0
    score += e_score
    breakdown.append(f"量比{burst_vr:.1f}:{e_score}")

    # F 异动后地量
    after_vols = volumes[burst_idx + 1:n_total - 1]
    f_score = 0
    avg_vr = 0.0
    if len(after_vols) >= 3:
        base_vol = float(np.mean(volumes[max(0, burst_idx - 20):burst_idx]))
        if base_vol > 0:
            avg_vr = float(np.mean(after_vols)) / base_vol
            if 0 < avg_vr <= 0.7: f_score = 1
    score += f_score
    breakdown.append(f"地量{avg_vr:.1f}:{f_score}")

    # G 跌破黄线快速收回
    g_score = 0
    below_streak = 0
    for jj in range(burst_idx + 1, n_total - 1):
        if closes[jj] < yellow_arr[jj]:
            below_streak += 1
        else:
            if 0 < below_streak <= 2:
                g_score = 1
            below_streak = 0
    score += g_score
    breakdown.append(f"快收回:{g_score}")

    # H 破黄总天数 ≤3
    below_total = sum(1 for jj in range(burst_idx + 1, n_total - 1)
                      if closes[jj] < yellow_arr[jj])
    h_score = 1 if below_total <= 3 else 0
    score += h_score
    breakdown.append(f"破黄{below_total}:{h_score}")

    # I 跳空扣分
    i_score = 0
    for jj in range(burst_idx + 2, n_total - 1):
        if lows[jj - 1] > 0 and highs[jj] < lows[jj - 1]:
            gap_pct = (lows[jj - 1] - highs[jj]) / lows[jj - 1] * 100
            if gap_pct >= 3.0: i_score -= 2
            elif gap_pct >= 1.0: i_score -= 1
        elif highs[jj - 1] > 0 and lows[jj] > highs[jj - 1]:
            gap_pct = (lows[jj] - highs[jj - 1]) / highs[jj - 1] * 100
            if gap_pct >= 3.0: i_score -= 1
    score += i_score
    breakdown.append(f"跳空:{i_score}")

    # J 量价背离扣分
    j_penalty = 0
    for jj in range(burst_idx + 1, n_total - 1):
        o, c = opens[jj], closes[jj]
        if o <= 0: continue
        vr = _prev_vol_ratio(volumes, jj)
        chg = (c - o) / o * 100
        if chg >= 5.0: continue
        if chg < 0:
            drop = -chg
            if drop >= 2.5 and vr >= 1.5: j_penalty -= 2
            elif drop >= 1.5 and vr >= 1.2: j_penalty -= 1
        else:
            if chg >= 2.0 and vr <= 0.4: j_penalty -= 1
            elif chg >= 2.0 and vr >= 2.5: j_penalty -= 1
    score += j_penalty
    breakdown.append(f"量价:{j_penalty}")

    return score, breakdown
# PLACEHOLDER_CHECK_ONE


def check_one(args: tuple) -> Optional[dict]:
    """(symbol, date) → {symbol, name, close, score, breakdown} or None

    B1 Small 选股：异动突破多因子打分 + 主板 + 价格 ≤ 100。
    """
    symbol, date = args
    name_map = _load_name_map()

    # b1_small 过滤：仅主板
    if not _is_main_board(symbol):
        return None

    # 加载数据
    csv_path = os.path.join(settings.DATA_DIR, f"{symbol}.csv")
    if not os.path.exists(csv_path):
        return None
    try:
        df = pd.read_csv(csv_path)
        df[KLineConstants.DATE] = pd.to_datetime(df[KLineConstants.DATE])
        for col in [KLineConstants.OPEN, KLineConstants.HIGH, KLineConstants.LOW,
                    KLineConstants.CLOSE, KLineConstants.VOLUME]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df[df[KLineConstants.DATE] <= pd.to_datetime(date)]
        df = df.sort_values(KLineConstants.DATE).tail(200).reset_index(drop=True)
    except Exception:
        return None

    if len(df) < 60:
        return None

    closes = df[KLineConstants.CLOSE].values.astype(float)
    opens = df[KLineConstants.OPEN].values.astype(float)
    highs = df[KLineConstants.HIGH].values.astype(float)
    lows = df[KLineConstants.LOW].values.astype(float)
    volumes = df[KLineConstants.VOLUME].values.astype(float)
    n_total = len(closes)
    cur_close = float(closes[-1])

    # b1_small 过滤：价格 ≤ 100
    if cur_close > MAX_PRICE:
        return None

    yellow_arr = _yellow_series(closes)
    white_arr = _white_series(closes)
    j_arr = _j_series(highs, lows, closes)
    dif_arr, dea_arr = _macd_series(closes)

    cur_yellow = float(yellow_arr[-1])
    cur_white = float(white_arr[-1])
    cur_j = float(j_arr[-1])

    # 条件 1: 多头格局
    if cur_white <= cur_yellow or cur_close < cur_yellow:
        return None

    # 条件 2: KDJ J < 阈值
    if cur_j >= KDJ_J_THRESHOLD:
        return None

    # 条件 3: 翻番过滤
    window = closes[-DOUBLED_LOOKBACK:] if len(closes) >= DOUBLED_LOOKBACK else closes
    win_low = float(np.min(window))
    if win_low > 0 and float(np.max(window)) / win_low >= DOUBLED_RATIO:
        return None

    # 条件 4: 异动突破
    N = BURST_LOOKBACK_DAYS
    if n_total < N + 6:
        return None

    candidates = []
    for i in range(max(5, n_total - N - 1), n_total - 1):
        o, c = opens[i], closes[i]
        if o <= 0 or c < o:
            continue
        chg = (c - o) / o * 100
        if chg < BURST_MIN_CHG or chg >= BURST_MAX_CHG:
            continue
        vol_r = _prev_vol_ratio(volumes, i)
        if vol_r < BURST_VOL_RATIO:
            continue
        recent_below = False
        for k in range(max(0, i - BURST_RECENT_BELOW_DAYS), i):
            if closes[k] <= yellow_arr[k]:
                recent_below = True
                break
        if not recent_below:
            continue
        if c <= yellow_arr[i]:
            continue
        candidates.append(i)

    if not candidates:
        return None

    # 条件 5: 异动后无放量大阴 + 打分 ≥ 阈值
    burst_idx = -1
    score = 0
    breakdown = []
    for ci in candidates:
        big_drop = False
        for jj in range(ci + 1, n_total - 1):
            o, c = opens[jj], closes[jj]
            if o <= 0: continue
            drop_pct = (o - c) / o * 100
            vol_r = _prev_vol_ratio(volumes, jj)
            if drop_pct > STABLE_DROP_PCT and vol_r > STABLE_DROP_VOL_RATIO:
                big_drop = True
                break
        if big_drop:
            continue
        cs, cb = _compute_score(ci, closes, opens, volumes, highs, lows,
                                yellow_arr, dif_arr, dea_arr, j_arr, n_total)
        if cs >= SCORE_THRESHOLD:
            burst_idx = ci
            score = cs
            breakdown = cb
            break

    if burst_idx < 0:
        return None

    return {
        "symbol": symbol,
        "name": name_map.get(symbol, symbol),
        "match_date": date,
        "close": round(cur_close, 2),
        "score": score,
        "breakdown": breakdown,
    }

