# V2 策略调优实施计划：板块化大盘过滤 + 胜率反推权重微调

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 V2 策略的最大回撤从 −33.95% 压到 ≤ −15%，同时保持总收益 +35~+45%、胜率 ≥ 65%。

**Architecture:** 两个独立可叠加的杠杆。杠杆 A 把"上证一刀切"的大盘判强弱改为按个股代码段（60/00/30/68）匹配对应指数（上证/深成/创业/上证 50），细化到候选股自身板块。杠杆 B 用现有 137 笔交易胜负分组，反推各维度权重并人工设档微调。每个杠杆独立 commit 作回退点。

**Tech Stack:** Python 3.12, pandas, numpy, ProcessPoolExecutor。无新增依赖。

**Spec:** `docs/superpowers/specs/2026-05-18-v2-tuning-sector-aware-design.md`

---

## File Structure

| 文件 | 角色 | 改动类型 |
|---|---|---|
| `tests/portfolio_b1_top2.py` | 组合回测主入口 | 修改：增加 `INDEX_MAP` / `pick_index_for` / `_load_index_dfs`；改造 `market_allow_buy` 与 `market_is_strong` 接收 symbol；主循环用候选板块判断进场与持仓上限 |
| `tests/scan_v2_style.py` | V2 评分函数 | 修改：`compute_v2_score` 接收可选 `weights` 字典；总分改为加权求和 |
| `tests/analyze_score_weights.py` | **新增** 维度差值分析脚本 | 创建：读取回测产物，按胜负分组对比 5 维度均值，输出 Δ 表与推荐权重档位 |
| `output/portfolio/b1_top2_*.json` | 回测产物（gitignored） | 写出 |
| `reports/score_weight_analysis.txt` | 权重分析报告（gitignored） | 写出 |

**单元划分原则**：板块过滤逻辑全部集中在 portfolio 层（不下沉到 scan）；评分函数本身无大盘概念，权重作为可选参数注入。这样 scan 仍可独立测试单股形态，portfolio 层负责所有"市场环境"决策。

---

## 任务清单（10 个 task）

### Task 1：实现 INDEX_MAP + pick_index_for（杠杆 A 第 1 步）

**Files:**
- Modify: `tests/portfolio_b1_top2.py:35-43`（在 `INDEX_SYMBOL` 常量附近）

**Why TDD here is light**：纯查表函数无副作用，写 5 行测试 + 5 行实现一气呵成。

- [ ] **Step 1: 写失败测试**

新增 `tests/test_pick_index.py`（项目目前无 pytest 框架，直接写 assert 脚本作冒烟测试）：

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

```bash
.venv/bin/python tests/test_pick_index.py
```
期望：`ImportError: cannot import name 'pick_index_for' from 'tests.portfolio_b1_top2'`

- [ ] **Step 3: 写最小实现**

在 `tests/portfolio_b1_top2.py` 第 43 行后（`INDEX_SYMBOL = "idx_000001_SH"` 那一行后）追加：

```python
INDEX_MAP = {
    "60": "idx_000001_SH",
    "00": "idx_399001_SZ",
    "30": "idx_399006_SZ",
    "68": "idx_000016_SH",
}
INDEX_DEFAULT = "idx_000001_SH"


def pick_index_for(symbol: str) -> str:
    """按代码前缀返回对应大盘指数 symbol。
    60→上证, 00→深成, 30→创业, 68→科创(用上证50平替), 其他→上证兜底。
    """
    return INDEX_MAP.get(symbol[:2], INDEX_DEFAULT)
```

- [ ] **Step 4: 跑测试确认通过**

```bash
.venv/bin/python tests/test_pick_index.py
```
期望：`pick_index_for: all OK`

- [ ] **Step 5: 不 commit**（这一步与 Task 2 一起 commit）

---

### Task 2：实现 _load_index_dfs（带日期校验）

**Files:**
- Modify: `tests/portfolio_b1_top2.py`（在 `pick_index_for` 之后追加函数）

- [ ] **Step 1: 写失败测试**

在 `tests/test_pick_index.py` 末尾追加：

```python
import pandas as pd
from tests.portfolio_b1_top2 import _load_index_dfs

# 4 个指数文件都齐 + 范围内
dfs = _load_index_dfs("2025-01-01", "2026-05-15")
assert "idx_000001_SH" in dfs, "上证应被加载"
assert "idx_399001_SZ" in dfs, "深成应被加载"
assert "idx_399006_SZ" in dfs, "创业板应被加载"
assert "idx_000016_SH" in dfs, "上证50应被加载"
for k, v in dfs.items():
    assert isinstance(v, pd.DataFrame), f"{k} 应为 DataFrame"
    assert len(v) > 0, f"{k} 应非空"
print("_load_index_dfs: all OK")
```

- [ ] **Step 2: 跑测试确认失败**

```bash
.venv/bin/python tests/test_pick_index.py
```
期望：`ImportError: cannot import name '_load_index_dfs'`

- [ ] **Step 3: 写实现**

在 `tests/portfolio_b1_top2.py` `pick_index_for` 之后追加：

```python
def _load_index_dfs(start_date: str, end_date: str) -> dict:
    """加载所有用到的指数 CSV，校验日期覆盖。
    缺失或日期不覆盖的指数 key 退化到 INDEX_DEFAULT 并打印 warning。
    返回 {idx_symbol: DataFrame}。
    """
    import logging
    logger = logging.getLogger(__name__)
    needed = set(INDEX_MAP.values()) | {INDEX_DEFAULT}
    out = {}
    start = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)
    for idx_sym in needed:
        df = load_csv(idx_sym)
        if df is None or df.empty:
            logger.warning(f"指数 {idx_sym} 缺失，退化到 {INDEX_DEFAULT}")
            out[idx_sym] = None
            continue
        first = df[KLineConstants.DATE].min()
        last = df[KLineConstants.DATE].max()
        if first > start or last < end:
            logger.warning(
                f"指数 {idx_sym} 日期范围 {first.date()}~{last.date()} "
                f"未覆盖回测区间 {start.date()}~{end.date()}，退化到 {INDEX_DEFAULT}"
            )
            out[idx_sym] = None
            continue
        out[idx_sym] = df
    # 退化处理：把 None 替换成 INDEX_DEFAULT 的 df
    default_df = out.get(INDEX_DEFAULT)
    if default_df is None:
        raise RuntimeError(f"INDEX_DEFAULT={INDEX_DEFAULT} 数据不可用，无法回测")
    return {k: (v if v is not None else default_df) for k, v in out.items()}
```

- [ ] **Step 4: 跑测试确认通过**

```bash
.venv/bin/python tests/test_pick_index.py
```
期望：两段都 OK。

- [ ] **Step 5: Commit**

```bash
git add tests/portfolio_b1_top2.py tests/test_pick_index.py
git commit -m "feat(portfolio): 加 INDEX_MAP/pick_index_for/_load_index_dfs，按板块映射指数"
```

---

### Task 3：market_allow_buy / market_is_strong 接收 symbol

**Files:**
- Modify: `tests/portfolio_b1_top2.py:124-146`

- [ ] **Step 1: 写测试**

在 `tests/test_pick_index.py` 末尾追加：

```python
from tests.portfolio_b1_top2 import market_allow_buy, market_is_strong

dfs = _load_index_dfs("2025-01-01", "2026-05-15")
# 关键日期：2025-05-15 上证 close > 大哥黄但 5 日斜率不一定 > 0
r1 = market_allow_buy("2025-05-15", "600000", dfs)
r2 = market_allow_buy("2025-05-15", "300001", dfs)
print(f"market_allow_buy 600000@2025-05-15 = {r1}")
print(f"market_allow_buy 300001@2025-05-15 = {r2}")
# 不强行断言具体值（取决于真实数据），只确保函数能跑通且返回 bool
assert isinstance(r1, bool) and isinstance(r2, bool)

s1 = market_is_strong("2025-05-15", "600000", dfs)
s2 = market_is_strong("2025-05-15", "300001", dfs)
print(f"market_is_strong 600000@2025-05-15 = {s1}")
print(f"market_is_strong 300001@2025-05-15 = {s2}")
assert isinstance(s1, bool) and isinstance(s2, bool)
print("market_*: all OK")
```

- [ ] **Step 2: 跑测试确认失败**

期望：`TypeError: market_allow_buy() takes 2 positional arguments but 3 were given`

- [ ] **Step 3: 改实现**

替换 `tests/portfolio_b1_top2.py:124-146` 整段为：

```python
def market_allow_buy(date: str, symbol: str, index_dfs: dict) -> bool:
    """大盘收盘 >= 大哥黄 才允许买入（按 symbol 选板块对应指数）。"""
    idx = index_dfs[pick_index_for(symbol)]
    hist = get_history_until(idx, date)
    if hist.empty or len(hist) < 30:
        return False
    closes = hist[KLineConstants.CLOSE].values.astype(float)
    yellow = B1Strategy._yellow_series(closes)
    return float(closes[-1]) >= float(yellow[-1])


def market_is_strong(date: str, symbol: str, index_dfs: dict) -> bool:
    """大盘强势：close >= 大哥黄 且 大哥黄 5 日斜率 > 0（按 symbol 选板块对应指数）。"""
    idx = index_dfs[pick_index_for(symbol)]
    hist = get_history_until(idx, date)
    if hist.empty or len(hist) < 30:
        return False
    closes = hist[KLineConstants.CLOSE].values.astype(float)
    yellow = B1Strategy._yellow_series(closes)
    cond_close = float(closes[-1]) >= float(yellow[-1])
    if len(yellow) >= 6 and float(yellow[-6]) > 0:
        slope_5 = (float(yellow[-1]) / float(yellow[-6])) - 1
    else:
        slope_5 = 0.0
    return cond_close and slope_5 > 0
```

- [ ] **Step 4: 跑测试确认通过**

```bash
.venv/bin/python tests/test_pick_index.py
```
期望：`market_*: all OK`，并打印两个交易日的 4 个布尔值。

- [ ] **Step 5: 不 commit**（与 Task 4 主循环改动一起 commit）

---

### Task 4：主循环改用 index_dfs 与候选板块判断

**Files:**
- Modify: `tests/portfolio_b1_top2.py:217-330`（run_backtest 函数体）

- [ ] **Step 1: 改 run_backtest 头部**

把 `tests/portfolio_b1_top2.py:221-224`（`index_df = load_csv(INDEX_SYMBOL)`...）替换为：

```python
    index_dfs = _load_index_dfs(start_date, end_date)
    index_df = index_dfs[INDEX_DEFAULT]  # 用作 trading_days 抽取的参考
    if index_df is None:
        print(f"未找到大盘数据 {INDEX_DEFAULT}.csv，回测中止")
        sys.exit(1)
```

- [ ] **Step 2: 改主循环里的市场判断**

替换 `tests/portfolio_b1_top2.py:246-250`（`for i, today in enumerate...` 之后到 `market_strong = ...`）为：

```python
    for i, today in enumerate(trading_days[:-1]):
        next_day = trading_days[i + 1]

        # ===== 1. 检查持仓的卖出信号（T 日数据判断） =====
        sells_today = []  # [(sym, reason, ratio)]
        for sym, pos in list(positions.items()):
            df = load_csv(sym)
            # 持仓股票按自身板块判强弱（决定止损宽紧）
            held_strong = market_is_strong(today, sym, index_dfs)
            reason, ratio = calc_sell_signal(pos, df, today, held_strong)
            if reason:
                sells_today.append((sym, reason, ratio))
```

- [ ] **Step 3: 改候选过滤逻辑**

替换 `tests/portfolio_b1_top2.py:290-303`（持仓不满 → 扫描候选补仓那段）为：

```python
        # ===== 3. 持仓不满 → 扫描候选补仓（按候选板块判强弱） =====
        if len(positions) < 2:
            tasks = [(s, today) for s in symbols]
            hits = []
            for fut in as_completed({pool.submit(_scan_worker, t): t for t in tasks}):
                r = fut.result()
                if r and r["symbol"] not in positions:
                    # 板块过滤：候选所属板块 close >= 大哥黄 才入池
                    if market_allow_buy(today, r["symbol"], index_dfs):
                        hits.append(r)
            hits.sort(key=lambda x: -x["score"])

            # 按候选板块强弱决定能补几个 slot
            picked = []
            for cand in hits:
                cand_strong = market_is_strong(today, cand["symbol"], index_dfs)
                # 候选板块强：可补到 2 只
                # 候选板块弱：仅在空仓时补 1 只
                if cand_strong:
                    if len(positions) + len(picked) < 2:
                        picked.append(cand)
                else:
                    if len(positions) == 0 and len(picked) == 0:
                        picked.append(cand)
                if len(positions) + len(picked) >= 2:
                    break

            top = picked
```

注意：`top` 后面那段 `if top: per_pos_cap = capital * 0.5; for cand in top: ...` 保持不变。

**重要缩进提醒**：原来 `if top:` 块（约 305-336 行）位于 `if slots > 0:` 与 `if market_ok:` 双层 if 内，缩进 16 空格。新逻辑下外层只有一个 `if len(positions) < 2:`，所以原 16 空格缩进的整段需要**统一减少 4 空格**（变成 12 空格），作为新 `if len(positions) < 2:` 的直接子块。改完用 `python -c "import ast; ast.parse(open('tests/portfolio_b1_top2.py').read())"` 校验语法没坏。

`slots` 旧变量已不需要，确保下面引用 `slots` 的地方都改成 `len(positions) + len(picked)` 或者直接用 `len(top)`。检查 `tests/portfolio_b1_top2.py:316`（`budget = min(per_pos_cap, cash / max(1, slots))`）改为：

```python
                        budget = min(per_pos_cap, cash / max(1, len(top)))
```

- [ ] **Step 4: 删除 skipped_market_days 相关代码**

板块化后没有"全市场禁买"概念，候选过滤改为单股粒度。需要清理：

1. `tests/portfolio_b1_top2.py:241` — 变量初始化 `skipped_market_days = 0` 改为保留（聚合函数仍接收此参数）
2. `tests/portfolio_b1_top2.py:337-338` — `else: skipped_market_days += 1` 整段删除（板块化后没有"全市场禁买"分支）
3. `tests/portfolio_b1_top2.py:316` — `budget = min(per_pos_cap, cash / max(1, slots))` 改为 `budget = min(per_pos_cap, cash / max(1, len(top)))`
4. `tests/portfolio_b1_top2.py:336` — `slots -= 1` 整行删除（新逻辑下 `picked` 数组已经决定了买几个，不需要 `slots` 计数器）

执行完后 `slots` 这个变量名只能出现在已经替换好的 Step 3 的注释里，不能再有任何 `slots = ...` / `slots -= 1` / `slots <= 0` 这类代码。grep 确认：

```bash
grep -n "slots" tests/portfolio_b1_top2.py
```
期望：只有注释和 `len(top)` 提到，没有 `slots` 变量赋值/修改。

- [ ] **Step 5: 烟雾测试 — 短区间回测能跑通**

```bash
.venv/bin/python tests/portfolio_b1_top2.py --start 2025-01-01 --end 2025-02-28 --workers 8
```
期望：跑完不报错，输出统计指标，无关于 `INDEX_SYMBOL` 的 NameError。

- [ ] **Step 6: Commit**

```bash
git add tests/portfolio_b1_top2.py tests/test_pick_index.py
git commit -m "feat(portfolio): 杠杆 A 落地——按候选板块判强弱过滤"
```

---

### Task 5：跑全区间回测，记录杠杆 A 表现

**Files:**
- Run: `tests/portfolio_b1_top2.py`

- [ ] **Step 1: 全区间回测**

```bash
.venv/bin/python tests/portfolio_b1_top2.py --start 2025-01-01 --end 2026-05-17 --workers 8
```
期望：跑完，回测产物在 `output/portfolio/b1_top2_2025-01-01_2026-05-17.json`。

- [ ] **Step 2: 提取关键指标**

```bash
.venv/bin/python -c "
import json, pandas as pd
with open('output/portfolio/b1_top2_2025-01-01_2026-05-17.json') as f:
    r = json.load(f)
s = r['stats']
print(f'=== 杠杆 A 后 ===')
print(f'总收益: {s[\"total_return_pct\"]:+.2f}%')
print(f'年化  : {s[\"annual_return_pct\"]:+.2f}%')
print(f'回撤  : {s[\"max_drawdown_pct\"]:.2f}%')
print(f'胜率  : {s[\"win_rate_pct\"]:.2f}%')
print(f'笔数  : {s[\"trades_total\"]}')
print(f'平均盈/亏: {s[\"avg_win_pct\"]:+.2f}% / {s[\"avg_loss_pct\"]:+.2f}%')
"
```

记录三组数：基线（+50.17% / −33.95% / 62.77%）vs A 后。

- [ ] **Step 3: 5 月回撤区间对比**

```bash
.venv/bin/python -c "
import json
with open('output/portfolio/b1_top2_2025-01-01_2026-05-17.json') as f:
    trades = json.load(f)['trades']
may = [t for t in trades if '2025-04-01' <= t['sell_date'] <= '2025-06-03']
print(f'5 月份回撤区间: {len(may)} 笔')
import numpy as np
pnls = [t['pnl_pct'] for t in may]
print(f'累计盈亏: {sum(pnls):+.2f}%')
print(f'平均盈亏: {np.mean(pnls) if pnls else 0:+.2f}%')
print(f'胜率: {sum(1 for p in pnls if p>0)}/{len(pnls)}' if pnls else '无交易')
"
```

期望：5 月份笔数从 16 减少到 ≤ 8 笔（板块过滤拦截了创业板/中小盘弱势股），累计亏损从 −46% 收窄到 −20% 内。

- [ ] **Step 4: 验证目标达成情况（软目标）**

人工核对（**这是软目标，未达成不阻塞 Task 6+；只在严重偏离时才停下来排查**）：
- 总收益 ≥ +35%（目标 +35~+45%）
- 最大回撤 ≤ −22%（A 单独的中间目标；最终 ≤ −15% 留给 A+B 一起达成）
- 胜率 ≥ 63%（应至少持平 62.77%）

**严重偏离的判定**：
- 总收益 < +20%（说明 A 拦得过狠）→ 停下排查
- 最大回撤反而扩大到 ≥ −38%（说明 A 改造引入 bug）→ 停下排查
- 胜率 < 50%（说明评分系统失常）→ 停下排查

只要不触发上述严重偏离，即使中间目标未达（如回撤 −25%）也继续走 Task 6。Task 6+B 仍有进一步压回撤空间。

- [ ] **Step 5: 不 commit**（结果是 gitignored 的 output/，commit 在 Task 4 已完成）

---

### Task 6：scan_v2_style 清理参数 + 支持权重注入

**Files:**
- Modify: `tests/scan_v2_style.py:64-66`（compute_v2_score 函数签名）
- Modify: `tests/scan_v2_style.py:136`（函数末尾 return）
- Modify: `tests/scan_v2_style.py:198-199`（check_one 调用处）
- Modify: `tests/scan_v2_style.py:188-196`（check_one 中计算 white_above_yellow / volatility_10 的死代码）

**背景**：当前 `compute_v2_score` 签名有 8 个参数（`close, trend_long, vol_ratio, chg_pct, kdj_j, long_slope, white_above_yellow, volatility_10`），但函数体只用了前 6 个——`white_above_yellow` 和 `volatility_10` 是早期试验留下的死参数。Task 6 同时清理掉这两个死参数 + 注入 `weights` 关键字。

- [ ] **Step 1: 写测试**

新增 `tests/test_v2_weights.py`：

```python
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

# 不能再用旧 8 参数签名（应当报错）
try:
    compute_v2_score(10.3, 10.0, 1.0, 0.0, 0.0, 0.01, 0.5, 2.0)
    raise AssertionError("旧 8 参数签名应已被清理，但调用居然成功了")
except TypeError:
    pass
print("compute_v2_score 签名清理 + weights: all OK")
```

- [ ] **Step 2: 跑测试确认失败**

```bash
.venv/bin/python tests/test_v2_weights.py
```
期望：
- 第一个 `compute_v2_score(...)` 调用就 TypeError，因为现版要求 8 参数，但调用只传 6 个

- [ ] **Step 3: 改函数签名 + 末尾权重注入**

修改 `tests/scan_v2_style.py:64-66`：

```python
def compute_v2_score(close: float, trend_long: float, vol_ratio: float,
                    chg_pct: float, kdj_j: float, long_slope: float,
                    weights: dict = None) -> tuple:
    """返回 (score, breakdown_dict)。校准自 b1_v2 数据。

    weights: {dim_name: float} 可选权重字典，默认所有维度权重 1.0。
    breakdown 中的子分不受权重影响（保留原始解释性），只影响最终 score 总和。
    """
```

修改 `tests/scan_v2_style.py:134-136`（原 `breakdown['趋势'] = round(s, 2)` 之后到 return 之间）：

```python
    breakdown['趋势'] = round(s, 2)
    score += s

    if weights:
        score = sum(weights.get(k, 1.0) * v for k, v in breakdown.items())
    return round(score, 2), breakdown
```

- [ ] **Step 4: 改 check_one 调用 + 删死代码**

定位 `tests/scan_v2_style.py:185-199`，当前长这样：

```python
    long_slope = ((yellow[-1] / yellow[-6] - 1)) if len(yellow) >= 6 and yellow[-6] > 0 else 0.0
    # 新增：短均线 vs 长均线（多头排列强度）
    white_above_yellow = (cur_white / cur_yellow - 1) * 100
    # 新增：10 日价格波动率（蓄势收敛特征）
    volatility_10 = float(np.std(closes[-10:]) / np.mean(closes[-10:]) * 100) if len(closes) >= 10 else 0

    score, breakdown = compute_v2_score(cur_close, cur_yellow, vol_ratio, chg_pct, cur_j,
                                         long_slope, white_above_yellow, volatility_10)
```

替换为：

```python
    long_slope = ((yellow[-1] / yellow[-6] - 1)) if len(yellow) >= 6 and yellow[-6] > 0 else 0.0

    score, breakdown = compute_v2_score(cur_close, cur_yellow, vol_ratio, chg_pct, cur_j,
                                         long_slope)
```

注意：保留 `cur_white` 计算（如果在文件其他地方还有引用），但 `white_above_yellow` 和 `volatility_10` 这两个变量整段删掉。

事后用 grep 校验：

```bash
grep -n "white_above_yellow\|volatility_10" tests/scan_v2_style.py
```
期望：无任何输出（两个变量已彻底清除）。

- [ ] **Step 5: 跑测试确认通过**

```bash
.venv/bin/python tests/test_v2_weights.py
```
期望：`compute_v2_score 签名清理 + weights: all OK`

- [ ] **Step 6: 烟雾测试 — 短区间回测仍能跑**

```bash
.venv/bin/python tests/portfolio_b1_top2.py --start 2025-01-01 --end 2025-02-28 --workers 8
```
期望：跑完不报错。结果可与 Task 5 不一致（如果 Task 5 用了带 white_above_yellow/volatility_10 的版本），但因为这两个参数从来未生效，结果应该完全相同。

- [ ] **Step 7: Commit**

```bash
git add tests/scan_v2_style.py tests/test_v2_weights.py
git commit -m "refactor(scan): 清理 compute_v2_score 死参数，加 weights 注入"
```

---

### Task 7：写 analyze_score_weights.py（计算 Δ 表）

**Files:**
- Create: `tests/analyze_score_weights.py`

**注意**：本 Task 依赖 Task 6 完成（compute_v2_score 现已 6 参数签名）。

- [ ] **Step 1: 写脚本主体**

```python
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

    # Task 6 完成后，compute_v2_score 是 6 位置参数 + 可选 weights
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
        f"{'维度':>6} {'胜均':>8} {'负均':>8} {'Δ':>+8} {'方向':>4} {'推荐权重':>8}",
        "-" * 50,
    ]
    for d in dims:
        win_avg = float(wins[d].mean()) if len(wins) else 0.0
        loss_avg = float(losses[d].mean()) if len(losses) else 0.0
        delta = win_avg - loss_avg
        direction = "↑" if delta > 0.5 else ("↓" if delta < -0.5 else "—")
        weight = recommend_weight(delta)
        out_lines.append(f"{d:>6} {win_avg:>+8.2f} {loss_avg:>+8.2f} {delta:>+8.2f} {direction:>4} {weight:>8.2f}")
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
```

- [ ] **Step 2: 跑脚本**

```bash
.venv/bin/python tests/analyze_score_weights.py output/portfolio/b1_top2_2025-01-01_2026-05-17.json
```

期望输出：表格列出 5 维度的胜组均值、负组均值、Δ、方向、推荐权重。脚本写入 `reports/score_weight_analysis.txt`。

- [ ] **Step 3: 人工审阅 Δ 表**

把表格贴到对话上下文里，判断哪些权重调整合理。

合理的判断范围：
- 「位置」「趋势」是核心维度，调整应保守（±20% 内）
- 「KDJ」「日内」可以激进调整（重要性低，调错代价小）
- 任何 Δ 接近 0（绝对值 < 0.3）的维度强制保留 1.0

- [ ] **Step 4: Commit 脚本**

```bash
git add tests/analyze_score_weights.py
git commit -m "feat(analyze): 权重分析脚本——按交易胜负反推 5 维度 Δ 与推荐档位"
```

---

### Task 8：在 scan_v2_style 引入 WEIGHTS 全局配置

**Files:**
- Modify: `tests/scan_v2_style.py`（顶部加 `WEIGHTS` 默认字典）
- Modify: `tests/scan_v2_style.py:198-199`（`check_one` 调 `compute_v2_score` 时传入 `weights=WEIGHTS`）

- [ ] **Step 1: 在 scan_v2_style.py 顶部加默认 WEIGHTS**

`tests/scan_v2_style.py` 第 30 行附近（紧跟在 `_NAME_MAP: dict = {}` 之前或之后）追加：

```python
# 5 维度权重（人工根据 analyze_score_weights.py 输出的 Δ 表设定）
# 默认全 1.0，等同未启用权重
WEIGHTS = {
    "位置": 1.0,
    "量能": 1.0,
    "日内": 1.0,
    "KDJ": 1.0,
    "趋势": 1.0,
}
```

- [ ] **Step 2: check_one 传入 WEIGHTS**

定位 Task 6 Step 4 修改后的调用处（应位于 `tests/scan_v2_style.py:198` 附近）：

```python
    score, breakdown = compute_v2_score(cur_close, cur_yellow, vol_ratio, chg_pct, cur_j,
                                         long_slope)
```

改为：

```python
    score, breakdown = compute_v2_score(cur_close, cur_yellow, vol_ratio, chg_pct, cur_j,
                                         long_slope, weights=WEIGHTS)
```

- [ ] **Step 3: 烟雾测试 — 默认 WEIGHTS 下回测结果应与 Task 5 完全一致**

```bash
.venv/bin/python tests/portfolio_b1_top2.py --start 2025-01-01 --end 2026-05-17 --workers 8
```

```bash
.venv/bin/python -c "
import json
with open('output/portfolio/b1_top2_2025-01-01_2026-05-17.json') as f:
    s = json.load(f)['stats']
print(f'A 后基线（默认 WEIGHTS=1.0）: 收益 {s[\"total_return_pct\"]:+.2f}% 回撤 {s[\"max_drawdown_pct\"]:.2f}%')
"
```

期望：与 Task 5 记录的指标完全一致（默认权重 = 不影响）。如有偏差说明 Task 6 改造引入了精度差异，需检查。

- [ ] **Step 4: Commit**

```bash
git add tests/scan_v2_style.py
git commit -m "feat(scan): 引入 WEIGHTS 全局配置，默认全 1.0 不影响行为"
```

---

### Task 9：根据 Δ 表设权重，跑 A+B 全区间回测

**Files:**
- Modify: `tests/scan_v2_style.py`（更新 `WEIGHTS` 字典数值）

- [ ] **Step 1: 重读 reports/score_weight_analysis.txt**

```bash
cat reports/score_weight_analysis.txt
```

- [ ] **Step 2: 人工设定 WEIGHTS**

根据 Δ 表中"推荐权重"列，但要按这些原则人工修订：
1. Δ 绝对值 < 0.3 的维度强制 1.0（无显著差异）
2. 「位置」「趋势」核心维度限制在 0.8~1.3（保护策略骨架）
3. 「KDJ」「日内」「量能」可按推荐档位

把 `tests/scan_v2_style.py` 的 `WEIGHTS` 字典更新为人工决定的数值。例如：

```python
WEIGHTS = {
    "位置": 1.2,   # 假设 Δ=0.7
    "量能": 1.0,
    "日内": 1.5,   # 假设 Δ=1.1
    "KDJ": 0.8,    # 假设 Δ=-0.6
    "趋势": 1.0,
}
```

具体数值取决于 Task 6 输出。

- [ ] **Step 3: 全区间回测**

```bash
.venv/bin/python tests/portfolio_b1_top2.py --start 2025-01-01 --end 2026-05-17 --workers 8
```

- [ ] **Step 4: 提取关键指标 + 与 A 后对比**

```bash
.venv/bin/python -c "
import json
with open('output/portfolio/b1_top2_2025-01-01_2026-05-17.json') as f:
    s = json.load(f)['stats']
print(f'A+B 后: 收益 {s[\"total_return_pct\"]:+.2f}% 年化 {s[\"annual_return_pct\"]:+.2f}% 回撤 {s[\"max_drawdown_pct\"]:.2f}% 胜率 {s[\"win_rate_pct\"]:.2f}% 笔数 {s[\"trades_total\"]}')
"
```

- [ ] **Step 5: 验证目标达成**

人工核对：
- [ ] 总收益 ≥ +35%（目标 +35~+45%）
- [ ] 最大回撤 ≤ −15%（**核心目标**）
- [ ] 胜率 ≥ 65%

如果 A+B 比 A 单独更差，回退 Task 9 的权重改动到默认 1.0。

- [ ] **Step 6: Commit**

```bash
git add tests/scan_v2_style.py
git commit -m "feat(scan): 杠杆 B 落地——按 Δ 表设 5 维度权重微调"
```

---

### Task 10：决定最终留存版本 + 文档化结果

**Files:**
- Modify: `docs/superpowers/specs/2026-05-18-v2-tuning-sector-aware-design.md`（追加"实施结果"章节）

- [ ] **Step 1: 对比三组指标**

把基线（+50.17% / −33.95%）、A 单独、A+B 三组指标列表对比。决定：
- 若 A+B 在所有指标上都不输 A 单独 → 留 A+B
- 若 A+B 收益更高但回撤更大 → 看是否符合"压回撤"目标，可能留 A 单独
- 若 A+B 回撤更小且收益降幅 < 5pp → 留 A+B

- [ ] **Step 2: 在 spec 末尾追加结果章节**

在 `docs/superpowers/specs/2026-05-18-v2-tuning-sector-aware-design.md` 末尾追加：

```markdown
## 实施结果（2026-05-18）

| 版本 | 总收益 | 年化 | 最大回撤 | 胜率 | 笔数 |
|---|:---:|:---:|:---:|:---:|:---:|
| 基线 | +50.17% | +38.66% | −33.95% | 62.77% | 137 |
| 杠杆 A | __% | __% | __% | __% | __ |
| 杠杆 A+B | __% | __% | __% | __% | __ |

**留存版本：** [A 单独 / A+B]，理由：__

**5 月份回撤区间对比：** 基线 16 笔累计 −46% → A 后 __ 笔累计 __%

**Δ 表关键观察：** [人工填写从 reports/score_weight_analysis.txt 看到的洞察]

**未达成的目标：** [若 max_drawdown 仍 > −15%，记录原因与下一步可能方向]
```

填好实际数值。

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-05-18-v2-tuning-sector-aware-design.md
git commit -m "docs: V2 调优实施结果 — 杠杆 A/B 对比与留存决定"
```

---

## 完成标准

执行完所有 Task 后：

- [ ] 7 个 commit 全部就位（Task 2/4/6/7/8/9/10）
- [ ] 全区间回测的最大回撤已压到 ≤ −20%（最低限度），最佳达 ≤ −15%
- [ ] 胜率 ≥ 63%
- [ ] 总收益 ≥ +35%
- [ ] spec 文档的"实施结果"章节有具体数据
- [ ] reports/score_weight_analysis.txt 已写出（gitignored 不入库，但本地存在）

如果回测结果未达成上述任一指标，需要在 Task 10 的 commit message 中明确记录"未达成"和原因，作为下一轮迭代的输入。
