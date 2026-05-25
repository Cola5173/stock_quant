"""v_master 全市场扫描

用法:
    python tests/scan_v_master_full.py 2026-05-23
    python tests/scan_v_master_full.py 2026-05-23 --workers 8

输出:
    selected/{yyyy-mm-dd}/v_master.json
"""
import argparse
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from glob import glob

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.config import settings
from api.schemas.kline_constants import KLineConstants
from api.strategy.v_master import VMasterStrategy


_NAME_MAP: dict = {}


def _load_name_map() -> dict:
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


def list_symbols() -> list:
    files = glob(os.path.join(settings.DATA_DIR, "*.csv"))
    out = []
    for f in files:
        n = os.path.basename(f).replace(".csv", "")
        if n.isdigit() and len(n) == 6:
            out.append(n)
    return sorted(out)


def _limit_rate(symbol: str, is_st: bool = False) -> float:
    if is_st:
        return 0.05
    if symbol.startswith("30") or symbol.startswith("68"):
        return 0.20
    return 0.10


def check_one(args: tuple):
    """对单只股票在 end_date 应用 v_master 完整买入逻辑，命中返回候选 dict 否则 None。"""
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
    volumes = df[KLineConstants.VOLUME].values.astype(float)
    n_total = len(closes)

    min_required = VMasterStrategy.min_bars_required(VMasterStrategy.divergence_lookback)
    if n_total < min_required:
        return None

    T = n_total - 1
    cur_close = float(closes[T])
    limit_rate = _limit_rate(symbol, is_st=False)

    # 涨停排除
    if T >= 1 and closes[T - 1] > 0:
        day_pct = (closes[T] - closes[T - 1]) / closes[T - 1]
        if day_pct >= limit_rate - 0.001:
            return None

    # 翻番过滤
    n = VMasterStrategy.doubled_lookback
    if n > 0 and n_total >= n:
        win = closes[-n:]
        valid = win[win > 0]
        if len(valid) >= 2:
            wmin = float(np.min(valid))
            wmax = float(np.max(valid))
            if wmin > 0 and wmax / wmin >= VMasterStrategy.doubled_ratio:
                return None

    # MACD
    dif, dea, macd_bar = VMasterStrategy._calc_macd(closes)

    # 1. 底背离
    if not VMasterStrategy._has_bottom_divergence(
        closes, dif, macd_bar, T,
        lookback=VMasterStrategy.divergence_lookback,
        min_gap=VMasterStrategy.divergence_min_gap,
    ):
        return None

    # 2. 量能放大
    if not VMasterStrategy._has_volume_surge(
        volumes, T,
        lookback=VMasterStrategy.vol_surge_lookback,
        ratio=VMasterStrategy.vol_surge_ratio,
        base_window=VMasterStrategy.vol_base_window,
    ):
        return None

    # 3. DIF 水上
    if dif[T] <= 0:
        return None

    # 4. 站稳黄白
    yellow = VMasterStrategy._calc_yellow(closes, T)
    white = VMasterStrategy._calc_white(closes, T)
    if yellow <= 0 or white <= 0:
        return None
    if cur_close <= yellow or cur_close <= white:
        return None

    # 量能放大日详情
    surge_idx = VMasterStrategy._find_vol_surge_day(
        volumes, T,
        lookback=VMasterStrategy.vol_surge_lookback,
        base_window=VMasterStrategy.vol_base_window,
    )
    surge_date = df[KLineConstants.DATE].iloc[surge_idx].date().isoformat()
    base_start = max(0, surge_idx - VMasterStrategy.vol_base_window)
    base_avg = float(np.mean(volumes[base_start:surge_idx]))
    surge_ratio = float(volumes[surge_idx] / base_avg) if base_avg > 0 else 0.0

    return {
        "symbol": symbol,
        "name": name_map.get(symbol, symbol),
        "match_date": end_date,
        "close": round(cur_close, 2),
        "dif": round(float(dif[T]), 3),
        "dea": round(float(dea[T]), 3),
        "yellow": round(yellow, 2),
        "white": round(white, 2),
        "vol_surge_date": surge_date,
        "vol_surge_ratio": round(surge_ratio, 2),
        "indicators": {
            "macd_bar": round(float(macd_bar[T]), 3),
            "above_yellow_pct": round((cur_close - yellow) / yellow * 100, 2),
            "above_white_pct": round((cur_close - white) / white * 100, 2),
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
                print(f"  进度 {done}/{len(tasks)}  命中 {len(results)}  "
                      f"{rate:.1f}/s  ETA {eta:.0f}s", flush=True)

    # 量能放大倍数越大越靠前
    results.sort(key=lambda x: -x["vol_surge_ratio"])

    folder = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "selected", args.date)
    os.makedirs(folder, exist_ok=True)
    out_path = os.path.join(folder, "v_master.json")
    out = {
        "scan_date": args.date,
        "strategy": "v_master",
        "total_scanned": len(symbols),
        "candidates_count": len(results),
        "candidates": results,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n命中 {len(results)} 只，已保存到 {out_path}")
    for r in results[:30]:
        print(f"  {r['symbol']} {r['name']}  量能放大{r['vol_surge_ratio']}x@{r['vol_surge_date']}  "
              f"close={r['close']}  DIF={r['dif']}  黄={r['yellow']} 白={r['white']}")


if __name__ == "__main__":
    main()
