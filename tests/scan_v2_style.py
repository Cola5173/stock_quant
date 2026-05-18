"""V2 风格扫描：长均线支撑位伏击评分（仿 touzikexue b1_v2 思路）

评分逻辑（基于 b1_v2 真实数据反推）：
- 价格相对长均线（大哥黄）的位置：在 [-1%, +6%] 内是最佳伏击区
- 量比：0.7~1.3 健康区间，>1.5 大幅扣分
- 当日涨跌：剧烈下跌（< -5%）扣分
- KDJ J：[-20, 30] 加分，避开极端区
- 长均线趋势向上：加分（多头格局）

用法:
    python tests/scan_v2_style.py 2026-05-15 --workers 8
"""
import os
import sys
import json
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from glob import glob
from typing import Optional

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.config import settings
from api.schemas.kline_constants import KLineConstants
from api.strategy.b1 import B1Strategy


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


def compute_v2_score(close: float, trend_long: float, vol_ratio: float,
                    chg_pct: float, kdj_j: float, long_slope: float,
                    white_above_yellow: float, volatility_10: float) -> tuple:
    """返回 (score, breakdown_dict)。校准自 b1_v2 数据"""
    breakdown = {}
    score = 0.0

    # 1. 价位评分：在长均线 [+1%, +7%] 是最佳伏击区，峰值在 +3.5%
    dev = (close / trend_long - 1) * 100 if trend_long > 0 else 0
    if 1.0 <= dev <= 7.0:
        s = 5.0 - abs(dev - 3.5) * 0.5
    elif 0 <= dev < 1.0:
        s = 3.0
    elif -2.0 <= dev < 0:
        s = 1.0
    elif dev < -2.0:
        s = -2.0 + dev * 0.6
    else:
        s = 5.0 - (dev - 7.0) * 1.2
    breakdown['位置'] = round(s, 2)
    score += s

    # 2. 量比评分
    if 0.8 <= vol_ratio <= 1.5:
        s = 2.5
    elif vol_ratio < 0.8:
        s = 1.5
    elif vol_ratio < 1.7:
        s = 1.0
    elif vol_ratio < 2.5:
        s = -2.0 - (vol_ratio - 1.7) * 2.0
    else:
        s = -5.0 - (vol_ratio - 2.5) * 3.0
    breakdown['量能'] = round(s, 2)
    score += s

    # 3. 当日涨跌
    if -3.0 <= chg_pct <= 3.0:
        s = 1.5
    elif chg_pct < -5.0:
        s = -2.0 + (chg_pct + 5.0) * 0.5
    elif chg_pct < -3.0:
        s = 0.0
    elif chg_pct > 5.0:
        s = -1.0
    else:
        s = 0.5
    breakdown['日内'] = round(s, 2)
    score += s

    # 4. KDJ J
    if -15 <= kdj_j <= 25:
        s = 1.5
    elif kdj_j < -25:
        s = -1.0
    elif kdj_j < -15:
        s = 0.5
    elif kdj_j > 50:
        s = -2.0
    else:
        s = 0.5
    breakdown['KDJ'] = round(s, 2)
    score += s

    # 5. 长均线斜率（多头加分）
    if long_slope > 0:
        s = 1.5 + min(long_slope * 100, 2.0)
    else:
        s = -1.0 + long_slope * 50
    breakdown['趋势'] = round(s, 2)
    score += s

    return round(score, 2), breakdown


def check_one(args: tuple):
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
    highs = df[KLineConstants.HIGH].values.astype(float)
    lows = df[KLineConstants.LOW].values.astype(float)
    if len(closes) < 30:
        return None

    if len(closes) >= 2 and closes[-2] > 0:
        pct = (closes[-1] - closes[-2]) / closes[-2] * 100
        limit = 20.0 if (symbol.startswith("30") or symbol.startswith("68")) else 10.0
        if pct >= limit - 0.1:
            return None

    yellow = B1Strategy._yellow_series(closes)
    white = pd.Series(closes).ewm(span=10, adjust=False).mean().ewm(span=10, adjust=False).mean().values
    j_arr = B1Strategy._j_series(highs, lows, closes)
    cur_close = float(closes[-1])
    cur_yellow = float(yellow[-1])
    cur_white = float(white[-1])
    if cur_yellow <= 0 or cur_white <= 0:
        return None

    if len(volumes) >= 6:
        vol_ma5 = float(np.mean(volumes[-6:-1]))
        vol_ratio = volumes[-1] / vol_ma5 if vol_ma5 > 0 else 1.0
    else:
        vol_ratio = 1.0

    chg_pct = ((closes[-1] / closes[-2] - 1) * 100) if len(closes) >= 2 and closes[-2] > 0 else 0.0
    cur_j = float(j_arr[-1])
    long_slope = ((yellow[-1] / yellow[-6] - 1)) if len(yellow) >= 6 and yellow[-6] > 0 else 0.0
    # 新增：短均线 vs 长均线（多头排列强度）
    white_above_yellow = (cur_white / cur_yellow - 1) * 100
    # 新增：10 日价格波动率（蓄势收敛特征）
    volatility_10 = float(np.std(closes[-10:]) / np.mean(closes[-10:]) * 100) if len(closes) >= 10 else 0

    score, breakdown = compute_v2_score(cur_close, cur_yellow, vol_ratio, chg_pct, cur_j,
                                         long_slope, white_above_yellow, volatility_10)

    return {
        "symbol": symbol,
        "name": name_map.get(symbol, symbol),
        "match_date": end_date,
        "close": round(cur_close, 2),
        "score": score,
        "breakdown": breakdown,
        "indicators": {
            "kdj_j": round(cur_j, 2),
            "trend_long": round(cur_yellow, 2),
            "vol_ratio": round(vol_ratio, 3),
            "chg_pct": round(chg_pct, 3),
            "long_slope": round(long_slope * 100, 3),
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("date")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--top", type=int, default=20)
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
            if done % 1000 == 0 or done == len(tasks):
                el = (datetime.now() - t0).total_seconds()
                print(f"  进度 {done}/{len(tasks)} 耗时 {el:.1f}s", flush=True)

    results.sort(key=lambda x: -x["score"])

    date_part = args.date.replace("-", "_")
    folder = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "selected", f"{date_part}_v2")
    os.makedirs(folder, exist_ok=True)
    out_path = os.path.join(folder, "result.json")
    out = {
        "scan_date": args.date,
        "strategy": "v2_style",
        "total_scanned": len(symbols),
        "candidates_count": len(results),
        "candidates": results,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n命中 {len(results)} 只，保存到 {out_path}")
    print(f"\n=== Top {args.top} ===")
    for r in results[:args.top]:
        ind = r["indicators"]
        bd = r["breakdown"]
        print(f"  {r['symbol']:>7} {r['name']:>10s}  分{r['score']:>5.1f}  "
              f"close={ind['trend_long']:>6.2f}*{r['close']/ind['trend_long']:.4f}  "
              f"vol_r={ind['vol_ratio']:>5.2f}  chg={ind['chg_pct']:>+5.2f}%  "
              f"J={ind['kdj_j']:>+5.1f}  [{' '.join(f'{k}{v:+.1f}' for k,v in bd.items())}]")


if __name__ == "__main__":
    main()
