# V2 策略调优：板块化大盘过滤 + 胜率反推权重微调

- 日期：2026-05-18
- 涉及代码：`tests/portfolio_b1_top2.py`、`tests/scan_v2_style.py`、新增 `tests/analyze_score_weights.py`
- 状态：设计中

## 背景

V2 伏击策略当前 16 个月全区间回测：

| 指标 | 数值 |
|---|---:|
| 总收益率 | +50.17% |
| 年化收益 | +38.66% |
| 最大回撤 | **−33.95%** |
| 交易笔数 | 137 |
| 胜率 | 62.77% |
| 平均盈/亏 | +19.42% / −3.14% |

最大回撤集中在 **2025-02-21 → 2025-06-20**（80 天，−33.95%）。该段上证指数仅跌 0.5%，但中小盘/创业板大幅走弱。当前 V2 把所有股票都用上证指数判强弱，导致弱市场段中小盘股被持续误判为「大盘安全」，反复入场磨损 16 笔，累计亏 −46%。

V2 已尝试且无效的回撤压缩方向：大盘破黄强清、大盘 5 日斜率双过滤、弱市冷却期、ML 模型选股、追加波动率/多头维度评分。

## 目标

| 目标 | 当前 | 目标值 |
|---|:---:|:---:|
| 总收益 | +50.17% | +35% ~ +45%（允许下降） |
| 最大回撤 | −33.95% | **≤ −15%**（核心目标） |
| 胜率 | 62.77% | ≥ 65% |
| 同区间回测 | 16 个月 | 不变 |

## 非目标

- 不重写选股逻辑，仅微调现有 5 维度评分
- 不引入新指标维度（之前试过波动率、多头排列均反效果）
- 不引入 ML 模型（小数据泛化失败已验证）
- 不引入新的资金管理算法（仓位规则保留 50%/单只 + 强市 2 只 / 弱市 1 只）
- 不改 9 级阶梯分批止盈、T+3 不涨即卖等卖出规则

## 设计

### 杠杆 A：板块化大盘过滤

#### 板块→指数映射

| 股票代码段 | 板块 | 大盘指数文件 |
|---|---|---|
| `60xxxx` | 上交所主板 | `idx_000001_SH`（上证指数） |
| `00xxxx` | 深交所主板 | `idx_399001_SZ`（深证成指） |
| `30xxxx` | 创业板 | `idx_399006_SZ`（创业板指） |
| `68xxxx` | 科创板 | `idx_000016_SH`（上证 50，平替） |
| 其他（`4`/`8`/`83`/`87` 等） | 北交所/未识别 | `idx_000001_SH`（上证兜底） |

> 科创板（68 头）历史数据中包含较多大盘股，无独立指数文件，选用上证 50 作为大盘平替；这是次优选择，未来如能补充科创 50 数据可替换。

#### 实现位

在 `portfolio_b1_top2.py` 增加：

```python
INDEX_MAP = {
    "60": "idx_000001_SH",
    "00": "idx_399001_SZ",
    "30": "idx_399006_SZ",
    "68": "idx_000016_SH",
}
INDEX_DEFAULT = "idx_000001_SH"

def pick_index_for(symbol: str) -> str:
    """按代码前缀返回对应大盘指数 symbol。"""
    return INDEX_MAP.get(symbol[:2], INDEX_DEFAULT)
```

回测启动时改为预加载所有指数 DataFrame 到字典 `index_dfs: Dict[str, pd.DataFrame]`，按需取用。

加载阶段对每个指数做日期覆盖校验：起止日期必须涵盖回测区间，否则该指数 key 退化到 `INDEX_DEFAULT`（上证）并 `logger.warning`。

#### 判断节奏改造

`market_allow_buy(date, index_df)` 和 `market_is_strong(date, index_df)` 增加 `symbol` 参数，函数体内逻辑保留不变（前者：`close >= 大哥黄`；后者：`close >= 大哥黄 且 大哥黄 5 日斜率 > 0`），仅替换索引数据来源：

```python
def market_allow_buy(date: str, symbol: str, index_dfs: Dict[str, pd.DataFrame]) -> bool:
    idx = index_dfs[pick_index_for(symbol)]
    # 沿用原 close >= 大哥黄 判断
    ...

def market_is_strong(date: str, symbol: str, index_dfs: Dict[str, pd.DataFrame]) -> bool:
    idx = index_dfs[pick_index_for(symbol)]
    # 沿用原 close >= 大哥黄 且 5 日斜率 > 0 判断
    ...
```

主循环两处调用相应改造：

**1. 扫描层面（候选阶段，T 日还没确定哪只票被买）**

不再做"全市场禁买"前置，改为**对每只产出的候选股单独判断**：候选股 X 产生后，立即检查 `market_allow_buy(today, X.symbol, index_dfs)`，不通过则从 Top-2 排序池剔除。

实现：在 `scan_check_one` 返回结果后追加一个本地过滤步骤——`hits = [r for r in hits if market_allow_buy(today, r["symbol"], index_dfs)]`。

**2. 持仓上限（决定补到 2 只还是 1 只）**

按候选股自身板块强度决定补仓上限：

```python
def can_add_slot(cand_symbol):
    cand_strong = market_is_strong(today, cand_symbol, index_dfs)
    if cand_strong:
        return len(positions) < 2  # 候选板块强：可补到 2 只
    else:
        return len(positions) == 0  # 候选板块弱：仅空仓时补 1 只
```

简化语义：
- 候选所属板块**强**：可以补到 2 只持仓
- 候选所属板块**弱**：只在空仓时补 1 只
- 已有的持仓不主动减——之前测过强清反而恶化

这保留了「弱市半仓」的原意，但「弱市」从全市场维度细化到了**候选股自身板块**维度。

### 杠杆 B：胜率反推权重微调

#### 数据来源

A 落地后跑一次 16 个月全区间回测，得到新的 `output/portfolio/b1_top2_*.json`。从该文件的 `trades[]` 列表读取每笔交易，含 `symbol`、`buy_date`、`pnl_pct`。

#### 分析脚本：`tests/analyze_score_weights.py`

```
输入：output/portfolio/b1_top2_*.json
输出：表格（terminal + 写入 reports/score_weight_analysis.txt）

每行一个维度（位置/量能/日内/KDJ/趋势），列：
- 胜组均值（pnl_pct > 0 的交易，回溯 buy_date 算的得分）
- 负组均值（pnl_pct ≤ 0 的交易）
- Δ = 胜组 − 负组
- 推荐方向：↑ if Δ > 0.5 / ↓ if Δ < −0.5 / − 不动
- 推荐档位：直接根据 Δ 输出对应权重系数（×1.5/×1.2/×1.0/×0.8/×0.5）
```

实现要点：脚本内复用 `scan_v2_style.compute_v2_score`，对每笔交易在其 `buy_date` 重新计算各维度得分（不是 score 总分，是各维度子分）。

#### 权重应用

`compute_v2_score` 返回 `(score, breakdown)`，breakdown 是 dict。增加权重字典：

```python
WEIGHTS = {
    "位置": 1.0,  # 默认
    "量能": 1.0,
    "日内": 1.0,
    "KDJ": 1.0,
    "趋势": 1.0,
}
```

总分计算改为：`score = sum(WEIGHTS[k] * v for k, v in breakdown.items())`

人工根据 Δ 表设权重：
- Δ ≥ 1.0：×1.5
- 0.5 ≤ Δ < 1.0：×1.2
- −0.5 < Δ < 0.5：×1.0（不动）
- −1.0 < Δ ≤ −0.5：×0.8
- Δ ≤ −1.0：×0.5

不自动取 Δ 直接乘——Δ 来自仅 137 笔样本，自动权重容易过拟合。人工审阅可剔除显然反直觉的差异（例如某段时间样本不平衡）。

### 实施与验证顺序

```
Step 1：实现 INDEX_MAP + pick_index_for + 两处判断改造（杠杆 A）
Step 2：全区间回测，记录基线
        ├ 看是否达到「回撤 ≤ −15% / 收益 ≥ +35%」
        └ 输出 5 月份回撤区间的交易明细对比（重点：被新过滤拦掉的票数 + 实际表现）
Step 3：commit「杠杆 A 落地」
Step 4：写 analyze_score_weights.py，输出 Δ 表
Step 5：根据 Δ 表人工设 WEIGHTS，跑 A+B 全区间回测
Step 6：对比 A 单独 vs A+B 表现，留更优版本
Step 7：commit「权重微调（B 落地）」
```

每步独立 commit，中间结果即使不理想也保留作回退点。

## 验证标准

| 步骤 | 验证内容 |
|---|---|
| Step 2 后 | 回测产出文件存在；总收益、最大回撤、胜率三项指标打印正确 |
| Step 2 后 | 交易明细中能观察到「被板块过滤拦掉的候选」对比（输出 log） |
| Step 5 后 | 全区间回测完成；权重应用对每笔交易的 score 影响合理（输出 5 个维度的加权前后对比） |

## 已知风险

1. **板块指数样本不一致**：4 个指数文件历史长度不同。需在加载阶段校验回测起止日期都有数据，缺失则退化到上证。
2. **5 月份场景特殊**：2025/02-06 的回撤是震荡熊市的特定形态，板块化过滤在该场景应有效，但**不能保证未来其他形态的熊市同样适用**。设计中已强调"先解决已知问题"。
3. **胜率反推权重过拟合**：137 笔样本统计显著性有限。设计强制人工审阅 Δ 表，并限制权重调整幅度（×0.5 ~ ×1.5），避免极端权重。
4. **科创板用上证 50 平替不精准**：Step 2 回测后需检查科创板（68）股票的命中数与表现，若发现明显偏差，未来补充科创 50 指数数据。

## 文件变更清单

新增：
- `tests/analyze_score_weights.py` — 维度差值分析脚本
- `docs/superpowers/specs/2026-05-18-v2-tuning-sector-aware-design.md` — 本文件

修改：
- `tests/portfolio_b1_top2.py` — 增加 INDEX_MAP / pick_index_for / 改造 market_allow_buy 与 market_is_strong / 主循环两处判断
- `tests/scan_v2_style.py` — `compute_v2_score` 接受可选 WEIGHTS 字典；总分计算改为加权求和
