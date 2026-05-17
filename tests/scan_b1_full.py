"""B1 全市场扫描（完整策略逻辑：5 关卡 + 多因子打分）

用法:
    python tests/scan_b1_full.py 2026-05-15
    python tests/scan_b1_full.py 2026-05-15 --workers 8

输出:
    selected/{yyyy_mm_dd}_b1/result.json
"""
import sys
import os
import json
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from glob import glob

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.config import settings
from api.schemas.kline_constants import KLineConstants
from api.strategy.b1 import B1Strategy
from api.indicator.indicators import calculate_KDJ, calculate_amplitude


_NAME_MAP: dict = {}


def _load_name_map() -> dict:
    """加载 stock_names.csv 为 {symbol: name} 映射"""
    global _NAME_MAP
    if _NAME_MAP:
        return _NAME_MAP
    csv_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "api", "resource", "stock_names.csv"
    )
    if not os.path.exists(csv_path):
        return {}
    try:
        df = pd.read_csv(csv_path, dtype={"symbol": str})
        _NAME_MAP = dict(zip(df["symbol"].astype(str).str.strip(),
                             df["name"].astype(str).str.strip()))
    except Exception:
        _NAME_MAP = {}
    return _NAME_MAP


class _ParamStub:
    red_window_size = B1Strategy.red_window_size
    macd_cross_lookback = B1Strategy.macd_cross_lookback
    divergence_min_gap_days = B1Strategy.divergence_min_gap_days
    divergence_price_max = B1Strategy.divergence_price_max
    doubled_lookback = B1Strategy.doubled_lookback
    doubled_ratio = B1Strategy.doubled_ratio
    _prev_vol_ratio = staticmethod(B1Strategy._prev_vol_ratio)


def _zx_white(closes: np.ndarray) -> np.ndarray:
    s = pd.Series(closes)
    return s.ewm(span=10, adjust=False).mean().ewm(span=10, adjust=False).mean().values


def list_symbols() -> list:
    files = glob(os.path.join(settings.DATA_DIR, "*.csv"))
    out = []
    for f in files:
        n = os.path.basename(f).replace(".csv", "")
        if n.isdigit() and len(n) == 6:
            out.append(n)
    return sorted(out)


def check_one(args: tuple):
    """对单只股票在 end_date 应用完整 B1 买入逻辑，匹配则返回候选 dict，否则 None。"""
    symbol, end_date = args
    name_map = _load_name_map()
    csv_path = os.path.join(settings.DATA_DIR, f"{symbol}.csv")
    if not os.path.exists(csv_path):
        return None
    try:
        df = pd.read_csv(csv_path)
        for col in [KLineConstants.OPEN, KLineConstants.HIGH, KLineConstants.LOW,
                    KLineConstants.CLOSE, KLineConstants.VOLUME]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df[KLineConstants.DATE] = pd.to_datetime(df[KLineConstants.DATE])
        df = df[df[KLineConstants.DATE] <= pd.to_datetime(end_date)]
        df = df.sort_values(KLineConstants.DATE).reset_index(drop=True)
    except Exception:
        return None

    if df.empty:
        return None
    last_date = df[KLineConstants.DATE].iloc[-1].date().isoformat()
    if last_date != end_date:
        return None

    closes = df[KLineConstants.CLOSE].values.astype(float)
    opens = df[KLineConstants.OPEN].values.astype(float)
    highs = df[KLineConstants.HIGH].values.astype(float)
    lows = df[KLineConstants.LOW].values.astype(float)
    volumes = df[KLineConstants.VOLUME].values.astype(float)

    n_total = len(closes)
    if n_total < B1Strategy.burst_lookback_days + 6:
        return None

    if n_total >= 2:
        prev_close = float(closes[-2])
        cur_close_raw = float(closes[-1])
        pct = (cur_close_raw - prev_close) / prev_close * 100 if prev_close > 0 else 0.0
        limit = 20.0 if (symbol.startswith("30") or symbol.startswith("68")) else 10.0
        if pct >= limit - 0.1:
            return None

    yellow = B1Strategy._yellow_series(closes)
    white = _zx_white(closes)
    j_arr = B1Strategy._j_series(highs, lows, closes)
    dif_arr, dea_arr = B1Strategy._macd_series(closes)

    cur_close = float(closes[-1])
    cur_white = float(white[-1])
    cur_yellow = float(yellow[-1])
    if cur_white <= cur_yellow or cur_close <= cur_yellow:
        return None

    cur_j = float(j_arr[-1])
    if cur_j >= B1Strategy.kdj_j_threshold:
        return None

    n_dbl = B1Strategy.doubled_lookback
    if n_dbl > 0 and len(closes) >= n_dbl:
        win = closes[-n_dbl:]
        wlow = float(np.min(win))
        whigh = float(np.max(win))
        ratio = whigh / wlow if wlow > 0 else 0.0
        if ratio >= B1Strategy.doubled_ratio:
            return None

    N = B1Strategy.burst_lookback_days
    candidates = []
    for i in range(max(5, n_total - N - 1), n_total - 1):
        o, c = opens[i], closes[i]
        if o <= 0 or c < o:
            continue
        chg = (c - o) / o * 100
        if chg < B1Strategy.burst_min_chg or chg >= B1Strategy.burst_max_chg:
            continue
        vol_r = B1Strategy._prev_vol_ratio(volumes, i)
        if vol_r < B1Strategy.burst_vol_ratio:
            continue
        recent_below = False
        for k in range(max(0, i - max(1, B1Strategy.burst_recent_below_days)), i):
            if closes[k] <= yellow[k]:
                recent_below = True
                break
        if not recent_below:
            continue
        if c <= yellow[i]:
            continue
        candidates.append(i)

    if not candidates:
        return None

    stub = _ParamStub()
    burst_idx = -1
    score = 0
    breakdown = []
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
            continue
        cs, cb = B1Strategy._compute_score(
            stub, ci, closes, opens, volumes, yellow,
            dif_arr, dea_arr, j_arr, n_total,
            highs, lows,
        )
        if cs >= B1Strategy.score_threshold:
            burst_idx = ci
            score = cs
            breakdown = cb
            break

    if burst_idx < 0:
        return None

    try:
        kdj_full = calculate_KDJ(df)
        amp = calculate_amplitude(df)
    except Exception:
        kdj_full = {"K": 0.0, "D": 0.0, "J": cur_j}
        amp = {"amplitude": 0.0}

    return {
        "symbol": symbol,
        "name": name_map.get(symbol, symbol),
        "match_date": end_date,
        "close": round(cur_close, 2),
        "score": int(score),
        "breakdown": breakdown,
        "burst_date": df[KLineConstants.DATE].iloc[burst_idx].date().isoformat(),
        "indicators": {
            "kdj_j": float(kdj_full.get("J", round(cur_j, 2))),
            "kdj_k": float(kdj_full.get("K", 0.0)),
            "kdj_d": float(kdj_full.get("D", 0.0)),
            "zx_white": round(cur_white, 2),
            "zx_yellow": round(cur_yellow, 2),
            "amplitude": float(amp.get("amplitude", 0.0)),
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("date", help="扫描日期 YYYY-MM-DD")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    symbols = list_symbols()
    print(f"扫描日: {args.date} | 股票总数: {len(symbols)} | 并发: {args.workers}")

    t0 = datetime.now()
    results = []
    tasks = [(s, args.date) for s in symbols]
    with ProcessPoolExecutor(max_workers=args.workers) as exe:
        futures = {exe.submit(check_one, t): t[0] for t in tasks}
        done = 0
        for fut in as_completed(futures):
            r = fut.result()
            if r:
                results.append(r)
            done += 1
            if done % 500 == 0 or done == len(tasks):
                el = (datetime.now() - t0).total_seconds()
                rate = done / el if el > 0 else 0
                eta = (len(tasks) - done) / rate if rate > 0 else 0
                print(f"  进度 {done}/{len(tasks)}  命中 {len(results)}  {rate:.1f}/s  ETA {eta:.0f}s",
                      flush=True)

    results.sort(key=lambda x: -x["score"])

    date_part = args.date.replace("-", "_")
    folder = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "selected", f"{date_part}_b1")
    os.makedirs(folder, exist_ok=True)
    out_path = os.path.join(folder, "result.json")
    out = {
        "scan_date": args.date,
        "strategy": "b1",
        "total_scanned": len(symbols),
        "candidates_count": len(results),
        "candidates": results,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n命中 {len(results)} 只，已保存到 {out_path}")
    for r in results[:30]:
        print(f"  {r['symbol']}  分{r['score']}  close={r['close']}  J={r['indicators']['kdj_j']}  "
              f"异动日={r['burst_date']}  [{' '.join(r['breakdown'])}]")


if __name__ == "__main__":
    main()
