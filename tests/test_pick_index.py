"""pick_index_for 单元测试 — 用 assert 直接执行。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.portfolio_b1_top2 import pick_index_for

assert pick_index_for("600000") == "idx_000001_SH", "上交主板应映上证"
assert pick_index_for("000001") == "idx_399001_SZ", "深主板应映深成"
assert pick_index_for("300001") == "idx_399006_SZ", "创业板应映创指"
assert pick_index_for("688001") == "idx_000016_SH", "科创板应映上证 50"
assert pick_index_for("830799") == "idx_000001_SH", "北交所兜底上证"
assert pick_index_for("400001") == "idx_000001_SH", "其他兜底上证"
print("pick_index_for: all OK")

import pandas as pd
from tests.portfolio_b1_top2 import _load_index_dfs

dfs = _load_index_dfs("2025-01-01", "2026-05-15")
assert "idx_000001_SH" in dfs, "上证应被加载"
assert "idx_399001_SZ" in dfs, "深成应被加载"
assert "idx_399006_SZ" in dfs, "创业板应被加载"
assert "idx_000016_SH" in dfs, "上证50应被加载"
for k, v in dfs.items():
    assert isinstance(v, pd.DataFrame), f"{k} 应为 DataFrame"
    assert len(v) > 0, f"{k} 应非空"
print("_load_index_dfs: all OK")
