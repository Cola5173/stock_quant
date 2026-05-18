"""权重分析：从回测产物反推 5 维度权重调整方向。

用法:
    python tests/analyze_score_weights.py output/portfolio/b1_top2_2025-01-01_2026-05-17.json
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from api.config import settings
from api.schemas.kline_constants import KLineConstants
from api.strategy.b1 import B1Strategy
from tests.scan_v2_style import compute_v2_score


def _load_breakdown_at(symbol: str, date: str):
    """加载股票 CSV 并截到 date 当日，返回 5 维度 breakdown 字典。"""
    csv = os.path.join(settings.DATA_DIR, f"{symbol}.csv")
    if not os.path.exists(csv):
        return None
    df = pd.read_csv(csv)
    for c in [KLineConstants.OPEN, KLineConstants.HIGH, KLineConstants.LOW,
              KLineConstants.CLOSE, KLineConstants.VOLUME]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df[KLineConstants.DATE] = pd.to_datetime(df[KLineConstants.DATE])
    df = df[df[KLineConstants.DATE] <= pd.to_datetime(date)].sort_values(KLineConstants.DATE).reset_index(drop=True)
    if len(df) < 30:
        return None
    closes = df[KLineConstants.CLOSE].values.astype(float)
    highs = df[KLineConstants.HIGH].values.astype(float)
    lows = df[KLineConstants.LOW].values.astype(float)
    volumes = df[KLineConstants.VOLUME].values.astype(float)

    yellow = B1Strategy._yellow_series(closes)
    j_arr = B1Strategy._j_series(highs, lows, closes)

    cur_close = float(closes[-1])
    cur_yellow = float(yellow[-1])
    if cur_yellow <= 0:
        return None
    vol_ma5 = float(np.mean(volumes[-6:-1])) if len(volumes) >= 6 else 0
    vol_ratio = volumes[-1] / vol_ma5 if vol_ma5 > 0 else 1.0
    chg_pct = (closes[-1] / closes[-2] - 1) * 100 if len(closes) >= 2 and closes[-2] > 0 else 0.0
    cur_j = float(j_arr[-1])
    long_slope = (yellow[-1] / yellow[-6] - 1) if len(yellow) >= 6 and yellow[-6] > 0 else 0.0

    _, breakdown = compute_v2_score(cur_close, cur_yellow, vol_ratio, chg_pct, cur_j, long_slope)
    return breakdown


def recommend_weight(delta: float) -> float:
    """根据胜负组得分差异推荐权重档位。"""
    if delta >= 1.0:
        return 1.5
    if delta >= 0.5:
        return 1.2
    if delta > -0.5:
        return 1.0
    if delta > -1.0:
        return 0.8
    return 0.5


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input_json", help="回测产物 b1_top2_*.json 路径")
    ap.add_argument("--output", default="reports/score_weight_analysis.txt")
    args = ap.parse_args()

    with open(args.input_json) as f:
        r = json.load(f)
    trades = r["trades"]
    print(f"输入: {args.input_json}, 共 {len(trades)} 笔交易")

    # 按 (symbol, buy_date) 去重（同一笔买入可能因分批止盈被多次记录）
    seen = set()
    uniq = []
    for t in trades:
        key = (t["symbol"], t["buy_date"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(t)
    print(f"去重后唯一买入: {len(uniq)}")

    rows = []
    skipped = 0
    for t in uniq:
        bd = _load_breakdown_at(t["symbol"], t["buy_date"])
        if bd is None:
            skipped += 1
            continue
        bd["pnl_pct"] = t["pnl_pct"]
        bd["symbol"] = t["symbol"]
        bd["buy_date"] = t["buy_date"]
        rows.append(bd)
    print(f"成功提特征: {len(rows)}, 跳过: {skipped}")

    if not rows:
        print("无数据可分析")
        return

    df = pd.DataFrame(rows)
    wins = df[df["pnl_pct"] > 0]
    losses = df[df["pnl_pct"] <= 0]

    dims = ["位置", "量能", "日内", "KDJ", "趋势"]
    out_lines = [
        f"=== V2 权重分析（基于 {len(df)} 笔唯一买入）===",
        f"胜组 {len(wins)} 笔 / 负组 {len(losses)} 笔",
        "",
        f"{'维度':>6} {'胜均':>8} {'负均':>8} {'Δ':>8} {'方向':>4} {'推荐权重':>8}",
        "-" * 50,
    ]
    for d in dims:
        win_avg = float(wins[d].mean()) if len(wins) else 0.0
        loss_avg = float(losses[d].mean()) if len(losses) else 0.0
        delta = win_avg - loss_avg
        direction = "↑" if delta > 0.5 else ("↓" if delta < -0.5 else "—")
        weight = recommend_weight(delta)
        delta_str = f"{delta:+.2f}"
        out_lines.append(f"{d:>6} {win_avg:+8.2f} {loss_avg:+8.2f} {delta_str:>8} {direction:>4} {weight:>8.2f}")
    out_lines.append("")
    out_lines.append(
        "说明：Δ ≥ 1.0 → ×1.5; ≥ 0.5 → ×1.2; ±0.5 内 → 不动; ≤ -0.5 → ×0.8; ≤ -1.0 → ×0.5"
    )

    text = "\n".join(out_lines)
    print()
    print(text)

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(f"\n已写入 {args.output}")


if __name__ == "__main__":
    main()
