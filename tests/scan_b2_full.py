"""B2 全市场扫描

逻辑：
- T-1 该股票必须是 B1 命中票（复用 scan_b1_full.check_one）
- T 日是「B2 确认 K」：放量中长阳、偏光头、收盘 > 开盘 > 昨收
- 形态识别（首期实现"多门重炮"，命中加分）

用法：
    python tests/scan_b2_full.py 2025-07-08
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
from api.strategy.b2 import B2Strategy
from tests.scan_b1_full import check_one as b1_check_one, _load_name_map


def list_symbols() -> list:
    files = glob(os.path.join(settings.DATA_DIR, "*.csv"))
    out = []
    for f in files:
        n = os.path.basename(f).replace(".csv", "")
        if n.isdigit() and len(n) == 6:
            out.append(n)
    return sorted(out)


def _prev_trading_date(df: pd.DataFrame, today: pd.Timestamp) -> pd.Timestamp:
    """从 df 中找 today 之前最近的一个交易日。"""
    prev = df[df[KLineConstants.DATE] < today]
    if prev.empty:
        return None
    return prev.iloc[-1][KLineConstants.DATE]


def _detect_duomen(df: pd.DataFrame, t_idx: int,
                   lookback: int, door_body_min: float,
                   door_vol_ratio: float, min_bears: int,
                   strict_press: bool) -> dict:
    """多门重炮形态识别。

    T 日（右门）往前 lookback 日内找另一根放量中阳（左门），
    中间至少 min_bears 根阴线，两门成交量都 ≥ 中间阴线最大成交量。

    返回 {"left_door_idx", "left_door_date", "bears_count", "left_vol", "right_vol", "bears_max_vol"}
    或 None。
    """
    opens = df[KLineConstants.OPEN].values.astype(float)
    closes = df[KLineConstants.CLOSE].values.astype(float)
    volumes = df[KLineConstants.VOLUME].values.astype(float)

    if t_idx < lookback + 5:
        return None

    right_vol = float(volumes[t_idx])

    # 候选"左门"：放量中阳；从近到远扫描，取最近一个满足条件的
    scan_start = max(5, t_idx - lookback)
    for i in range(t_idx - 2, scan_start, -1):
        o, c = opens[i], closes[i]
        if o <= 0 or c <= o:
            continue
        body_pct = (c - o) / o * 100
        if body_pct < door_body_min:
            continue
        # 量比相对前 5 日均量
        prev_avg_vol = float(np.mean(volumes[max(0, i - 5):i]))
        if prev_avg_vol <= 0:
            continue
        if volumes[i] / prev_avg_vol < door_vol_ratio:
            continue

        # 中间阴线统计（i+1 到 t_idx-1）
        middle_o = opens[i + 1: t_idx]
        middle_c = closes[i + 1: t_idx]
        middle_v = volumes[i + 1: t_idx]
        bear_mask = middle_c < middle_o
        bears_count = int(np.sum(bear_mask))
        if bears_count < min_bears:
            continue

        # 两门量能 ≥ 中间阴线最大量
        bears_max_vol = float(np.max(middle_v[bear_mask])) if bears_count > 0 else 0.0
        if strict_press:
            if volumes[i] < bears_max_vol or right_vol < bears_max_vol:
                continue

        return {
            "left_door_idx": int(i),
            "left_door_date": str(df.iloc[i][KLineConstants.DATE].date()),
            "bears_count": bears_count,
            "left_vol": round(float(volumes[i]), 2),
            "right_vol": round(right_vol, 2),
            "bears_max_vol": round(bears_max_vol, 2),
        }

    return None


def check_one(args: tuple):
    """单股票 B2 检查：T-1 是 B1 + T 日 B2 确认 K + 形态识别。"""
    symbol, t_date = args
    csv_path = os.path.join(settings.DATA_DIR, f"{symbol}.csv")
    if not os.path.exists(csv_path):
        return None
    try:
        df = pd.read_csv(csv_path)
        for col in [KLineConstants.OPEN, KLineConstants.HIGH, KLineConstants.LOW,
                    KLineConstants.CLOSE, KLineConstants.VOLUME]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df[KLineConstants.DATE] = pd.to_datetime(df[KLineConstants.DATE])
        df = df.sort_values(KLineConstants.DATE).reset_index(drop=True)
    except Exception:
        return None

    if df.empty:
        return None

    today = pd.to_datetime(t_date)
    today_rows = df[df[KLineConstants.DATE] == today]
    if today_rows.empty:
        return None
    t_idx = int(today_rows.index[0])
    if t_idx < 1:
        return None

    # T-1 日 B1 检查（用 T-1 的实际日期，不一定是 t_date - 1）
    t_minus_1 = df.iloc[t_idx - 1][KLineConstants.DATE]
    b1_result = b1_check_one((symbol, t_minus_1.date().isoformat()))
    if b1_result is None:
        return None

    # T 日 B2 确认 K：放量中长阳 + 偏光头 + 收盘 > 开盘 > 昨收
    today_bar = df.iloc[t_idx]
    yesterday_bar = df.iloc[t_idx - 1]
    o = float(today_bar[KLineConstants.OPEN])
    c = float(today_bar[KLineConstants.CLOSE])
    h = float(today_bar[KLineConstants.HIGH])
    prev_c = float(yesterday_bar[KLineConstants.CLOSE])
    if o <= 0 or c <= o:
        return None
    body_pct = (c - o) / o * 100
    if body_pct < B2Strategy.b2_body_min_pct:
        return None
    if o <= prev_c:  # 必须开高
        return None

    # 量比相对前 5 日均量
    volumes = df[KLineConstants.VOLUME].values.astype(float)
    prev_avg = float(np.mean(volumes[max(0, t_idx - 5):t_idx]))
    if prev_avg <= 0:
        return None
    vol_ratio = volumes[t_idx] / prev_avg
    if vol_ratio < B2Strategy.b2_vol_ratio_min:
        return None

    # 上影线 / 实体（光头特征）
    body = c - o
    upper_shadow = h - c
    if body > 0 and upper_shadow / body > B2Strategy.b2_upper_shadow_max:
        return None

    # 形态识别：多门重炮
    duomen = _detect_duomen(
        df, t_idx,
        lookback=B2Strategy.duomen_lookback,
        door_body_min=B2Strategy.duomen_door_body_min,
        door_vol_ratio=B2Strategy.duomen_door_vol_ratio,
        min_bears=B2Strategy.duomen_min_bears,
        strict_press=B2Strategy.duomen_strict_press,
    )

    # 评分：B1 基础分 + B2 加分
    score = int(b1_result.get("score", 0))
    breakdown = list(b1_result.get("breakdown", []))
    breakdown.insert(0, f"B1基:{score}")

    if duomen:
        score += 3
        breakdown.append(f"多门重炮:3")
    if vol_ratio >= 3.0:
        score += 2
        breakdown.append(f"B2量比{vol_ratio:.1f}:2")
    elif vol_ratio >= 2.0:
        score += 1
        breakdown.append(f"B2量比{vol_ratio:.1f}:1")
    if body_pct >= 5.0:
        score += 1
        breakdown.append(f"B2实体{body_pct:.1f}%:1")
    if body > 0 and upper_shadow / body <= 0.1:
        score += 1
        breakdown.append("严格光头:1")

    name_map = _load_name_map()
    return {
        "symbol": symbol,
        "name": name_map.get(symbol, symbol),
        "match_date": t_date,
        "b1_match_date": t_minus_1.date().isoformat(),
        "b1_burst_date": b1_result.get("burst_date"),
        "close": round(c, 2),
        "score": score,
        "breakdown": breakdown,
        "pattern": "多门重炮" if duomen else "顺势而为",
        "duomen": duomen,
        "indicators": b1_result.get("indicators", {}),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("date", help="扫描日期 YYYY-MM-DD（B2 日 = T 日）")
    parser.add_argument("--workers", type=int, default=8)
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
            try:
                r = fut.result()
            except Exception:
                r = None
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

    folder = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "selected", args.date)
    os.makedirs(folder, exist_ok=True)
    out_path = os.path.join(folder, "b2.json")
    out = {
        "scan_date": args.date,
        "strategy": "b2",
        "total_scanned": len(symbols),
        "candidates_count": len(results),
        "candidates": results,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n命中 {len(results)} 只，已保存到 {out_path}")
    for r in results[:30]:
        pattern_tag = f"[{r['pattern']}]"
        print(f"  {r['symbol']} {r['name']:<8} 分{r['score']} {pattern_tag} "
              f"close={r['close']} B1={r['b1_match_date']} 异动={r['b1_burst_date']}")


if __name__ == "__main__":
    main()
