"""B1 Small 策略参数扫描

跑多组参数组合，找出综合分（收益 - 回撤 + 胜率加权）最优的配置。

用法：
    .venv/bin/python tests/sweep_b1_small.py
"""
import os
import re
import subprocess
import sys
from datetime import datetime

# 默认基线参数
BASELINE = {
    "weak_stop": 3.0,
    "strong_stop": 5.0,
    "t5_days": 5,
    "t5_gain": 3.0,        # 已优化：从 2% 提到 3%
    "tp_levels": "8,16,24",
    "score_threshold": 5,
    "burst_exhaustion": 15.0,
    "burst_pullback": 5.0,
}

# 在 T5-Gain3 基线上进一步精细扫描
SWEEPS = [
    {"label": "Baseline(t5g3)", **BASELINE},
    # 时间止损天数微调
    {"label": "T4-Gain3", **BASELINE, "t5_days": 4},
    {"label": "T6-Gain3", **BASELINE, "t5_days": 6},
    {"label": "T7-Gain3", **BASELINE, "t5_days": 7},
    # T5 涨幅阈值进一步
    {"label": "T5-Gain2.5", **BASELINE, "t5_gain": 2.5},
    {"label": "T5-Gain4",   **BASELINE, "t5_gain": 4.0},
    {"label": "T5-Gain5",   **BASELINE, "t5_gain": 5.0},
    # 止损结合
    {"label": "Stop2/4+G3", **BASELINE, "weak_stop": 2.0, "strong_stop": 4.0},
    {"label": "Stop2/6+G3", **BASELINE, "weak_stop": 2.0, "strong_stop": 6.0},
    {"label": "Stop2.5/5+G3", **BASELINE, "weak_stop": 2.5},
    {"label": "Stop3/7+G3", **BASELINE, "strong_stop": 7.0},
    # 止盈结合
    {"label": "TP紧+G3",   **BASELINE, "tp_levels": "5,10,15"},
    {"label": "TP6/12+G3", **BASELINE, "tp_levels": "6,12,18"},
    {"label": "TP松+G3",   **BASELINE, "tp_levels": "10,20,30"},
    # 进一步组合
    {"label": "Combo-X", **BASELINE, "weak_stop": 2.0, "strong_stop": 6.0, "tp_levels": "6,12,18"},
    {"label": "Combo-Y", **BASELINE, "t5_days": 4, "tp_levels": "6,12,18"},
    {"label": "Combo-Z", **BASELINE, "t5_days": 6, "weak_stop": 2.5, "tp_levels": "6,12,18"},
    {"label": "Combo-T", **BASELINE, "t5_gain": 4.0, "tp_levels": "6,12,18"},
]

START = "2025-01-01"
END = "2026-05-18"
CAPITAL = 200000
WORKERS = 8


def run_one(cfg):
    cmd = [
        ".venv/bin/python", "tests/portfolio_b1_small.py",
        "--start", START, "--end", END,
        "--capital", str(CAPITAL), "--workers", str(WORKERS),
        "--out", "/tmp/sweep_tmp.json",
        "--quiet",
        "--weak-stop", str(cfg["weak_stop"]),
        "--strong-stop", str(cfg["strong_stop"]),
        "--t5-days", str(cfg["t5_days"]),
        "--t5-gain", str(cfg["t5_gain"]),
        "--tp-levels", cfg["tp_levels"],
        "--score-threshold", str(cfg["score_threshold"]),
        "--burst-exhaustion", str(cfg["burst_exhaustion"]),
        "--burst-pullback", str(cfg["burst_pullback"]),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    out = res.stdout + res.stderr
    m = re.search(
        r"RET=([+-]?\d+\.?\d*)%\s+DD=([+-]?\d+\.?\d*)%\s+WR=([+-]?\d+\.?\d*)%\s+TRADES=(\d+)\s+AVG_WIN=([+-]?\d+\.?\d*)%\s+AVG_LOSS=([+-]?\d+\.?\d*)%",
        out
    )
    if not m:
        return None
    return {
        "ret": float(m.group(1)),
        "dd": float(m.group(2)),
        "wr": float(m.group(3)),
        "trades": int(m.group(4)),
        "avg_win": float(m.group(5)),
        "avg_loss": float(m.group(6)),
    }


def score(r):
    """综合分：收益 - |回撤| × 0.5 + 胜率 × 0.3"""
    if r is None:
        return -999
    return r["ret"] - abs(r["dd"]) * 0.5 + r["wr"] * 0.3


def main():
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    print(f"参数扫描开始: {START} ~ {END}, {len(SWEEPS)} 组配置")
    print(f"{'='*100}")
    print(f"{'#':>3} {'配置':<22} {'收益':>10} {'回撤':>10} {'胜率':>8} {'笔数':>6} {'平赢':>8} {'平亏':>8} {'综合':>10}")
    print(f"{'-'*100}")
    results = []
    t0 = datetime.now()
    for i, cfg in enumerate(SWEEPS, 1):
        r = run_one(cfg)
        s = score(r) if r else -999
        if r is None:
            print(f"{i:>3} {cfg['label']:<22} 失败")
        else:
            print(f"{i:>3} {cfg['label']:<22} "
                  f"{r['ret']:>+9.2f}% {r['dd']:>+9.2f}% "
                  f"{r['wr']:>7.2f}% {r['trades']:>6d} "
                  f"{r['avg_win']:>+7.2f}% {r['avg_loss']:>+7.2f}% "
                  f"{s:>+9.2f}",
                  flush=True)
        results.append((cfg, r, s))
    elapsed = (datetime.now() - t0).total_seconds()
    print(f"{'='*100}")
    print(f"耗时 {elapsed:.0f}s")

    # Top 5
    valid = [(c, r, s) for c, r, s in results if r is not None]
    valid.sort(key=lambda x: -x[2])
    print(f"\n=== Top 5 综合分 ===")
    for c, r, s in valid[:5]:
        print(f"  {c['label']:<22} 综合 {s:+.2f}  收益 {r['ret']:+.2f}%  回撤 {r['dd']:+.2f}%  胜率 {r['wr']:.2f}%")


if __name__ == "__main__":
    main()
