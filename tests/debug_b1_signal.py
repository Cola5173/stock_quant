"""
B1 信号漏买排查脚本
输入 symbol + date，加载该票数据，逐关卡检查 B1 策略买入条件，定位卡掉点。

用法:
    python tests/debug_b1_signal.py 601778 2025-12-30
    python tests/debug_b1_signal.py 605168 2025-12-22
    python tests/debug_b1_signal.py 002929 2025-03-25
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.config import settings
from api.schemas.kline_constants import KLineConstants
from api.strategy.b1 import B1Strategy


class _ParamStub:
    """提供 B1Strategy 类常量的轻量代理，用于把 instance method 当函数调用。"""
    red_window_size = B1Strategy.red_window_size
    macd_cross_lookback = B1Strategy.macd_cross_lookback
    divergence_min_gap_days = B1Strategy.divergence_min_gap_days
    divergence_price_max = B1Strategy.divergence_price_max
    doubled_lookback = B1Strategy.doubled_lookback
    doubled_ratio = B1Strategy.doubled_ratio
    _prev_vol_ratio = staticmethod(B1Strategy._prev_vol_ratio)


def load_data(symbol: str, end_date: str) -> pd.DataFrame:
    csv_path = os.path.join(settings.DATA_DIR, f"{symbol}.csv")
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"未找到 {csv_path}")
    df = pd.read_csv(csv_path)
    for col in [KLineConstants.OPEN, KLineConstants.HIGH, KLineConstants.LOW,
                KLineConstants.CLOSE, KLineConstants.VOLUME]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df[KLineConstants.DATE] = pd.to_datetime(df[KLineConstants.DATE])
    df = df[df[KLineConstants.DATE] <= pd.to_datetime(end_date)]
    df = df.sort_values(KLineConstants.DATE).reset_index(drop=True)
    return df


def _zx_white(closes: np.ndarray) -> np.ndarray:
    """趋势白 = EMA(EMA(C,10),10)"""
    s = pd.Series(closes)
    return s.ewm(span=10, adjust=False).mean().ewm(span=10, adjust=False).mean().values


def check_b1(symbol: str, end_date: str):
    df = load_data(symbol, end_date)
    if df.empty:
        print(f"❌ {symbol} 无数据")
        return

    last_date = df[KLineConstants.DATE].iloc[-1].date()
    print(f"=== {symbol} 截止 {last_date}（共 {len(df)} 根 bar）===")

    closes = df[KLineConstants.CLOSE].values.astype(float)
    opens = df[KLineConstants.OPEN].values.astype(float)
    highs = df[KLineConstants.HIGH].values.astype(float)
    lows = df[KLineConstants.LOW].values.astype(float)
    volumes = df[KLineConstants.VOLUME].values.astype(float)
    dates = df[KLineConstants.DATE].dt.date.values

    n_total = len(closes)
    if n_total < B1Strategy.burst_lookback_days + 6:
        print(f"❌ 数据不足 {B1Strategy.burst_lookback_days + 6} 根，跳过")
        return

    # ===== 关卡 0：涨停 / 数据完整性（回测层面会先于策略关卡触发） =====
    if n_total >= 2:
        prev_close = float(closes[-2])
        cur_close_raw = float(closes[-1])
        pct = (cur_close_raw - prev_close) / prev_close * 100 if prev_close > 0 else 0.0
        # 涨跌停限制（粗略：30/68 开头 20%，其余 10%；不区分 ST）
        if symbol.startswith("30") or symbol.startswith("68"):
            limit = 20.0
        else:
            limit = 10.0
        at_upper = pct >= limit - 0.1
        print(f"\n[0] 涨跌停 / 数据")
        print(f"    前收={prev_close:.2f}  收盘={cur_close_raw:.2f}  涨跌={pct:+.2f}%  涨停阈值={limit}%")
        if at_upper:
            print(f"    ❌ 涨停（回测会跳过买入）")
            # 不 return，继续看后面关卡，便于发现真因
        else:
            print(f"    ✓ 非涨停")

    yellow = B1Strategy._yellow_series(closes)
    white = _zx_white(closes)
    j_arr = B1Strategy._j_series(highs, lows, closes)
    dif_arr, dea_arr = B1Strategy._macd_series(closes)

    # ===== 关卡 1：多头格局 =====
    cur_close = closes[-1]
    cur_white = float(white[-1])
    cur_yellow = float(yellow[-1])
    print(f"\n[1] 多头格局")
    print(f"    收盘={cur_close:.2f}  趋势白={cur_white:.2f}  大哥黄={cur_yellow:.2f}")
    if cur_white <= cur_yellow:
        print(f"    ❌ 卡掉：趋势白({cur_white:.2f}) <= 大哥黄({cur_yellow:.2f})")
        return
    if cur_close <= cur_yellow:
        print(f"    ❌ 卡掉：收盘({cur_close:.2f}) <= 大哥黄({cur_yellow:.2f})")
        return
    print("    ✓ 通过")

    # ===== 关卡 2：J 超卖 =====
    cur_j = float(j_arr[-1])
    print(f"\n[2] J 超卖")
    print(f"    J={cur_j:.2f}  阈值={B1Strategy.kdj_j_threshold}")
    if cur_j >= B1Strategy.kdj_j_threshold:
        print(f"    ❌ 卡掉：J({cur_j:.2f}) >= 阈值({B1Strategy.kdj_j_threshold})")
        return
    print("    ✓ 通过")

    # ===== 关卡 3：翻番过滤 =====
    n_dbl = B1Strategy.doubled_lookback
    if n_dbl > 0 and len(closes) >= n_dbl:
        win = closes[-n_dbl:]
        wlow = float(np.min(win))
        whigh = float(np.max(win))
        ratio = whigh / wlow if wlow > 0 else 0.0
        print(f"\n[3] 翻番过滤（最近 {n_dbl} 日）")
        print(f"    最低={wlow:.2f}  最高={whigh:.2f}  比例={ratio:.2f}x  阈值={B1Strategy.doubled_ratio}x")
        if ratio >= B1Strategy.doubled_ratio:
            print(f"    ❌ 卡掉：已涨幅 {ratio:.2f}x >= 阈值 {B1Strategy.doubled_ratio}x")
            return
        print("    ✓ 通过")

    # ===== 关卡 4：异动突破候选 =====
    N = B1Strategy.burst_lookback_days
    candidates = []
    near_misses = []
    for i in range(max(5, n_total - N - 1), n_total - 1):
        o, c = opens[i], closes[i]
        if o <= 0 or c < o:
            continue
        chg = (c - o) / o * 100
        vol_r = B1Strategy._prev_vol_ratio(volumes, i)

        miss_reasons = []
        if chg < B1Strategy.burst_min_chg:
            miss_reasons.append(f"涨幅{chg:.1f}%<{B1Strategy.burst_min_chg}")
        elif chg >= B1Strategy.burst_max_chg:
            miss_reasons.append(f"涨幅{chg:.1f}%>={B1Strategy.burst_max_chg}")
        if vol_r < B1Strategy.burst_vol_ratio:
            miss_reasons.append(f"量比{vol_r:.2f}<{B1Strategy.burst_vol_ratio}")

        recent_below = False
        for k in range(max(0, i - max(1, B1Strategy.burst_recent_below_days)), i):
            if closes[k] <= yellow[k]:
                recent_below = True
                break
        if not recent_below:
            miss_reasons.append("前5天未触黄")
        if c <= yellow[i]:
            miss_reasons.append(f"收盘{c:.2f}<=黄{yellow[i]:.2f}")

        if miss_reasons:
            if chg >= 1.5 and vol_r >= 0.9:
                near_misses.append((dates[i], chg, vol_r, "; ".join(miss_reasons)))
        else:
            candidates.append(i)

    print(f"\n[4] 异动突破候选（回看 {N} 日）")
    print(f"    候选数量={len(candidates)}")
    if not candidates:
        print(f"    ❌ 卡掉：无合规异动")
        if near_misses:
            print(f"    最近接近的阳线（前 8 条）：")
            for d, chg, vr, reasons in near_misses[-8:]:
                print(f"      {d} 涨{chg:.2f}% 量比{vr:.2f}  原因: {reasons}")
        return
    last_ci = candidates[-1]
    print(f"    最后候选: idx={last_ci} 日期={dates[last_ci]}  共 {len(candidates)} 个")
    print("    ✓ 通过")

    # ===== 关卡 5：异动后无放量大阴 + 打分 ≥ 阈值 =====
    print(f"\n[5] 异动后无放量大阴 + 打分（阈值 {B1Strategy.score_threshold}）")
    stub = _ParamStub()
    burst_idx = -1
    score = 0
    breakdown = []
    rejected = []
    for ci in candidates:
        big_drop = False
        for jj in range(ci + 1, n_total - 1):
            o, c = opens[jj], closes[jj]
            if o <= 0:
                continue
            drop_pct = (o - c) / o * 100
            vol_r = B1Strategy._prev_vol_ratio(volumes, jj)
            if drop_pct > B1Strategy.stable_drop_pct and vol_r > B1Strategy.stable_drop_vol_ratio:
                big_drop = True
                break
        if big_drop:
            rejected.append((dates[ci], "放量大阴线"))
            continue
        cs, cb = B1Strategy._compute_score(
            stub, ci, closes, opens, volumes, yellow,
            dif_arr, dea_arr, j_arr, n_total,
        )
        if cs >= B1Strategy.score_threshold:
            burst_idx = ci
            score = cs
            breakdown = cb
            break
        rejected.append((dates[ci], f"分{cs}<{B1Strategy.score_threshold} [{' '.join(cb)}]"))

    if burst_idx < 0:
        print(f"    ❌ 卡掉：所有候选被拒")
        for d, reason in rejected[-10:]:
            print(f"      {d}: {reason}")
        return
    print(f"    ✓ 通过：burst_idx={burst_idx} 日期={dates[burst_idx]} 分数={score}")
    print(f"      明细: {' '.join(breakdown)}")

    print(f"\n✅ 全部关卡通过——应当买入 close={cur_close:.2f}")


def main():
    parser = argparse.ArgumentParser(description="B1 漏买排查")
    parser.add_argument("symbol", help="6 位代码，如 601778")
    parser.add_argument("date", help="检查日期 YYYY-MM-DD（作为该 bar 的截止日）")
    args = parser.parse_args()
    check_b1(args.symbol, args.date)


if __name__ == "__main__":
    main()
