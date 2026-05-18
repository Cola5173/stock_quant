"""测试 compute_v2_score 的权重注入与签名清理。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.scan_v2_style import compute_v2_score

# 默认权重（全 1.0），新签名只接受 6 个位置参数
score_default, bd = compute_v2_score(
    close=10.3, trend_long=10.0, vol_ratio=1.0, chg_pct=0.0, kdj_j=0.0, long_slope=0.01
)
print(f"默认: score={score_default}, breakdown={bd}")
assert isinstance(score_default, float)
assert set(bd.keys()) == {"位置", "量能", "日内", "KDJ", "趋势"}

# 全部 ×2
weights_x2 = {k: 2.0 for k in bd.keys()}
score_x2, bd_x2 = compute_v2_score(
    close=10.3, trend_long=10.0, vol_ratio=1.0, chg_pct=0.0, kdj_j=0.0, long_slope=0.01,
    weights=weights_x2,
)
print(f"权重×2: score={score_x2}")
assert abs(score_x2 - score_default * 2) < 0.01, f"score_x2 应≈ score_default*2，实际 {score_x2} vs {score_default*2}"
assert bd_x2["位置"] == bd["位置"], "breakdown 子分应不受权重影响"

# 部分维度调整
weights_partial = {"位置": 1.5, "量能": 1.0, "日内": 1.0, "KDJ": 1.0, "趋势": 1.0}
score_partial, _ = compute_v2_score(
    close=10.3, trend_long=10.0, vol_ratio=1.0, chg_pct=0.0, kdj_j=0.0, long_slope=0.01,
    weights=weights_partial,
)
expected_partial = score_default + bd["位置"] * 0.5
assert abs(score_partial - expected_partial) < 0.01

# 不能再用旧 8 参数签名
try:
    compute_v2_score(10.3, 10.0, 1.0, 0.0, 0.0, 0.01, 0.5, 2.0)
    raise AssertionError("旧 8 参数签名应已被清理，但调用居然成功了")
except TypeError:
    pass
print("compute_v2_score 签名清理 + weights: all OK")
