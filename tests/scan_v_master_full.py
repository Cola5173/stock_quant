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

    opens = df[KLineConstants.OPEN].values.astype(float)
    highs = df[KLineConstants.HIGH].values.astype(float)
    lows = df[KLineConstants.LOW].values.astype(float)
    closes = df[KLineConstants.CLOSE].values.astype(float)
    volumes = df[KLineConstants.VOLUME].values.astype(float)
    n_total = len(closes)

    min_required = VMasterStrategy.min_bars_required(
        VMasterStrategy.lookback_v, VMasterStrategy.down_lookback
    )
    if n_total < min_required:
        return None

    T = n_total - 1
    is_kc = VMasterStrategy._is_kc_board(symbol)
    limit_rate = _limit_rate(symbol, is_st=False)

    # 当日涨停（一字板）排除
    if T >= 1 and closes[T - 1] > 0:
        day_pct = (closes[T] - closes[T - 1]) / closes[T - 1] * 100
        if day_pct >= limit_rate * 100 - 0.1:
            return None

    # 翻番过滤
    n = VMasterStrategy.doubled_lookback
    if n > 0 and n_total >= n:
        win = closes[-n:]
        wlow = float(np.min(win))
        whigh = float(np.max(win))
        if wlow > 0 and whigh / wlow >= VMasterStrategy.doubled_ratio:
            return None

    # V 锚
    v_idx = VMasterStrategy._find_v_anchor(
        opens, highs, lows, closes, volumes, T,
        lookback_v=VMasterStrategy.lookback_v,
        cooldown_min=VMasterStrategy.cooldown_min,
        cooldown_max=VMasterStrategy.cooldown_max,
        down_lookback=VMasterStrategy.down_lookback,
        down_drawdown=VMasterStrategy.down_drawdown,
        v_body_min_pct=(VMasterStrategy.v_body_min_pct_kc if is_kc
                        else VMasterStrategy.v_body_min_pct),
        v_vol_ratio=VMasterStrategy.v_vol_ratio,
        limit_rate=limit_rate,
    )
    if v_idx is None:
        return None

    # 洗盘期
    if not VMasterStrategy._check_washout(
        opens, closes, lows, volumes, v_idx, T,
        washout_drop_pct=VMasterStrategy.washout_drop_pct,
        washout_drop_vol_ratio=VMasterStrategy.washout_drop_vol_ratio,
    ):
        return None

    # 决策日
    ok, today_vr, ma5, ma10, ma20 = VMasterStrategy._check_today_confirm(
        opens, closes, volumes, v_idx, T,
        t_body_min_pct=(VMasterStrategy.t_body_min_pct_kc if is_kc
                        else VMasterStrategy.t_body_min_pct),
        t_vol_ratio=VMasterStrategy.t_vol_ratio,
        limit_rate=limit_rate,
    )
    if not ok:
        return None

    v_vr = VMasterStrategy._vol_ratio(volumes, v_idx)
    v_low = float(lows[v_idx])
    v_idx_date = df[KLineConstants.DATE].iloc[v_idx].date().isoformat()
    cur_close = float(closes[T])

    return {
        "symbol": symbol,
        "name": name_map.get(symbol, symbol),
        "match_date": end_date,
        "close": round(cur_close, 2),
        "v_idx_date": v_idx_date,
        "v_low": round(v_low, 2),
        "v_vol_ratio": round(v_vr, 2),
        "today_vol_ratio": round(today_vr, 2),
        "indicators": {
            "ma5": round(ma5, 2),
            "ma10": round(ma10, 2),
            "ma20": round(ma20, 2),
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

    # V 锚量比越大越靠前
    results.sort(key=lambda x: -x["v_vol_ratio"])

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
        print(f"  {r['symbol']}  V量比{r['v_vol_ratio']}  close={r['close']}  "
              f"V锚={r['v_idx_date']} V低={r['v_low']}  今量比{r['today_vol_ratio']}  "
              f"MA5={r['indicators']['ma5']} MA10={r['indicators']['ma10']} MA20={r['indicators']['ma20']}")


if __name__ == "__main__":
    main()
