# 核心仓位买卖规则设计稿

- 日期：2026-05-25
- 作者：cola1213
- 状态：draft → 待审阅
- 关联文档：[投资理念](../../concept/investment-philosophy.md)、[历史触发分析](../../concept/historical-trigger-analysis.md)

---

## 1. 背景与目标

### 1.1 问题陈述

[投资理念](../../concept/investment-philosophy.md) 给出了核心仓的**原则性约束**：

- 核心仓 70%，由四个 ETF 组成（纳指 100 / 黄金 / 低波红利 / 沪深 300）
- 每月固定从现金流划 60-70% 定投
- 每年 1 月再平衡
- PE 到历史 90% 分位以上减仓
- 绝不割肉、绝不情绪操作

但**缺乏可执行规则**：定投怎么分配？什么时候加仓？什么时候减仓？再平衡具体怎么调？

本文档解决这个空白：**为核心仓设计一套完整、可量化、可机械执行的买卖规则。**

### 1.2 设计目标

1. **不赌择时**：不预测市场顶/底，用规则替代判断
2. **对抗人性**：用机械化规则锁死"觉得贵就停止定投"等情绪化操作
3. **渐进式响应**：极端低估/高估时分级响应，不 all-in 也不 all-out
4. **资金来源严守铁律**：不动用安全资产，加仓子弹来自机动定投的积累
5. **3-5 年时间维度**：参数适配年轻人的中期周期，不为 10 年熊市做过度准备

### 1.3 与卫星仓的边界

| 维度 | 卫星仓（已有系统） | 核心仓（本设计） |
|------|------------------|----------------|
| 标的 | 个股（周期反转） | ETF（4 个宽基/行业宽基） |
| 决策依据 | 技术指标（MACD/量能/均线） | 估值分位（PE/PB） |
| 操作频率 | 月度级，集中出手 | 月度定投 + 季度检查 + 年度再平衡 |
| 目标 | 博超额收益 | 吃市场平均 |
| 止损 | -15% 硬止损 | 绝不割肉 |

本文档**只覆盖核心仓**，不影响现有卫星仓系统。

---

## 2. 总体架构

核心仓规则由**五个子模块**组成，按时间维度从短到长排列：

```
月度定投（每月）
  ↓
子弹积累与释放（持续监控，估值触发）
  ↓
减仓规则（持续监控，估值触发）
  ↓
清仓后渐进恢复（清仓后专属）
  ↓
年度再平衡（每年 1 月）
```

所有规则**共享一组核心配置**：

```python
CORE_TARGET_ALLOCATION = {
    "纳指100":  0.30,  # 30%
    "黄金":     0.20,  # 20%
    "低波红利": 0.25,  # 25%
    "沪深300": 0.25,  # 25%
}

MONTHLY_CASH_FLOW = 10000  # 月度可投现金流（示例值，按实际调整）
MUST_INVEST_RATIO = 0.50   # 必投比例
FLEXIBLE_RATIO = 0.50      # 机动比例
BULLET_MAX_MONTHS = 9      # 子弹上限月数
```

---

## 3. 模块一：月度定投

### 3.1 资金拆分

月度现金流 1W → 拆成两部分：

```
月度定投 10000 元
├── 必投部分 50% = 5000 元 ← 雷打不动，按目标比例分配
└── 机动部分 50% = 5000 元 ← 看估值动态分配
```

### 3.2 必投部分（5000 元）

**规则：无脑按目标比例分配，不管估值。**

```python
def allocate_must_invest(amount=5000):
    return {
        "纳指100":  amount * 0.30,  # 1500
        "黄金":     amount * 0.20,  # 1000
        "低波红利": amount * 0.25,  # 1250
        "沪深300": amount * 0.25,  # 1250
    }
```

**例外条件（仅一种）：清仓后渐进恢复期，详见模块四。**

### 3.3 机动部分（5000 元）

**规则：根据 4 个 ETF 的当前 PE 分位动态分配。**

```python
def allocate_flexible_invest(amount=5000, pe_percentiles: dict[str, float]):
    """
    pe_percentiles: {"纳指100": 0.76, "黄金": 0.55, ...}
    """
    # 计算每个 ETF 的权重系数
    weights = {}
    for etf, pe_pct in pe_percentiles.items():
        if pe_pct < 0.30:
            weights[etf] = 1.5   # 低估，加权
        elif pe_pct < 0.70:
            weights[etf] = 1.0   # 中性，正常
        elif pe_pct < 0.90:
            weights[etf] = 0.5   # 偏高，少投
        else:
            weights[etf] = 0.0   # 极端高估，不投
    
    # 按权重 × 目标比例分配
    total_weight = sum(weights[etf] * CORE_TARGET_ALLOCATION[etf] 
                       for etf in weights)
    
    if total_weight == 0:
        # 全部高估，机动资金不投，转入子弹池
        return None  # 信号：积累子弹
    
    allocation = {}
    for etf in weights:
        allocation[etf] = (amount * weights[etf] * CORE_TARGET_ALLOCATION[etf] 
                          / total_weight)
    return allocation
```

### 3.4 黄金的特殊处理

黄金没有 PE/PB，需要替代估值指标：

**方案：金价 vs 10 年均价的偏离度**

```python
def gold_valuation_percentile(current_price, history_10y_prices):
    """
    用历史价格分位数替代 PE 分位数
    """
    return sum(p < current_price for p in history_10y_prices) / len(history_10y_prices)
```

后续如果有更好的指标（如金银比、实际利率），可以替换。

### 3.5 输出示例

**场景：2026 年 5 月**
- 纳指 PE 76% → 0.5x
- 黄金 价格 55% 分位 → 1.0x
- 红利 PE 35% → 1.0x
- 沪深 PE 86% → 0.5x

机动 5000 元分配：
- 总权重 = 0.5×0.30 + 1.0×0.20 + 1.0×0.25 + 0.5×0.25 = 0.725
- 纳指：5000 × (0.5×0.30) / 0.725 = 1034
- 黄金：5000 × (1.0×0.20) / 0.725 = 1379
- 红利：5000 × (1.0×0.25) / 0.725 = 1724
- 沪深：5000 × (0.5×0.25) / 0.725 = 862

**本月实际投入（必投 + 机动）：**
- 纳指：1500 + 1034 = 2534
- 黄金：1000 + 1379 = 2379
- 红利：1250 + 1724 = 2974
- 沪深：1250 + 862 = 2112

---

## 4. 模块二：子弹积累与释放

### 4.1 子弹来源

当机动部分不投时（全部 ETF > 90% 分位），那 5000 元**不流失**，而是进入"子弹池"。

**子弹池按目标比例分仓：**

```python
class BulletPool:
    def __init__(self):
        # 每个 ETF 有独立子弹池
        self.pools = {etf: 0.0 for etf in CORE_TARGET_ALLOCATION}
    
    def accumulate(self, amount):
        """机动资金没投出去时，按目标比例分到各子弹池"""
        for etf, ratio in CORE_TARGET_ALLOCATION.items():
            self.pools[etf] += amount * ratio
    
    def total(self):
        return sum(self.pools.values())
```

### 4.2 子弹上限（9 个月）

```
上限 = 月度机动 × 9 = 5000 × 9 = 45000 元

按目标比例分仓后：
├── 纳指子弹池上限 = 45000 × 0.30 = 13500 元
├── 黄金子弹池上限 = 45000 × 0.20 = 9000 元
├── 红利子弹池上限 = 45000 × 0.25 = 11250 元
└── 沪深子弹池上限 = 45000 × 0.25 = 11250 元
```

**到达上限后：** 机动资金转入"必投流"，按必投比例分配（即所有 1W 都按目标比例投，不再积累子弹）。

### 4.3 子弹释放（三档触发）

**单 ETF 独立判断，分三档：**

```python
def check_bullet_release(etf, pe_percentile, bullet_pool):
    """
    返回该 ETF 本次应释放的子弹金额
    """
    pool_max = BULLET_MAX_TOTAL * CORE_TARGET_ALLOCATION[etf]
    third = pool_max / 3
    
    available = bullet_pool[etf]
    
    # 状态机：根据已释放档位决定下一档
    if pe_percentile < 0.15:  # 三档
        return min(available, third)  # 释放剩余的最后 1/3
    elif pe_percentile < 0.25:  # 二档
        return min(available, third)  # 释放 1/3
    elif pe_percentile < 0.40:  # 一档
        return min(available, third)  # 释放 1/3
    else:
        return 0
```

**关键规则：**

1. **每档只释放对应仓位的 1/3**，不一次性 all-in
2. **打完后通过"高估时不投"自然恢复**，不强制重置
3. **同档位不会重复触发**——一旦该档位的 1/3 被打出，需要恢复后才能再次触发
4. **跨档位连续触发**：如果 PE 从 30% 直接跌到 10%，可以连续触发一档 + 二档 + 三档

### 4.4 状态记录

每个 ETF 维护一个"已释放档位"标记：

```python
class BulletState:
    def __init__(self, etf):
        self.etf = etf
        self.tier1_released = False  # < 40% 分位档
        self.tier2_released = False  # < 25% 分位档
        self.tier3_released = False  # < 15% 分位档
    
    def reset_tier(self, tier):
        """子弹池恢复到该档额度后，重置该档标记"""
        if tier == 1: self.tier1_released = False
        if tier == 2: self.tier2_released = False
        if tier == 3: self.tier3_released = False
    
    def reset_all(self):
        """该 ETF 估值回到 > 50% 分位时，所有档位重置"""
        self.tier1_released = False
        self.tier2_released = False
        self.tier3_released = False
```

### 4.5 强制释放（防止永远积累）

**触发条件：** 子弹池满 9 个月（达到上限）。

**执行：**
- 在下一次季度检查（3/6/9/12 月初）时强制执行
- 选择当前估值最低的 ETF（即使没到 40% 分位）
- 释放该 ETF 子弹池的 1/3

```python
def force_release_check(quarter_check_date):
    if bullet_pool.total() >= BULLET_MAX_TOTAL:
        # 找估值最低的 ETF
        lowest_etf = min(CORE_ETFS, key=lambda x: pe_percentiles[x])
        amount = bullet_pool.pools[lowest_etf] / 3
        execute_buy(lowest_etf, amount)
```

---

## 5. 模块三：减仓规则

### 5.1 三档触发（与加仓对称）

**单 ETF 独立判断，PE 分位触发：**

| 档位 | 触发条件 | 卖出比例 | 资金去向 |
|------|---------|---------|---------|
| 一档 | PE > 75% 分位 | 卖 1/3 持仓 | 100% 转入现金流池 |
| 二档 | PE > 85% 分位 | 再卖 1/3 持仓 | 50% 现金流 + 50% 安全资产 |
| 三档 | PE > 95% 分位 | 卖最后 1/3（清仓） | 100% 转入安全资产 |

### 5.2 卖出动作的精确定义

**"1/3 持仓"的口径：**

指**触发时该 ETF 的当前持仓市值的 1/3**，不是"目标比例的 1/3"。

```python
def calculate_sell_amount(etf, current_holding_value, tier):
    """
    current_holding_value: 该 ETF 当前持仓市值
    tier: 1, 2, 3
    """
    return current_holding_value / 3
```

### 5.3 资金去向的逻辑

```python
def route_sell_proceeds(amount, tier):
    if tier == 1:  # > 75% 分位
        # 估值偏高但未极端，钱留在风险资产体系内
        cash_flow_pool += amount
    
    elif tier == 2:  # > 85% 分位
        # 半仓离场，留半仓继续接其他低估机会
        cash_flow_pool += amount * 0.5
        safe_asset += amount * 0.5
    
    elif tier == 3:  # > 95% 分位
        # 极端高估，全部转入安全资产
        safe_asset += amount
```

### 5.4 状态记录

与加仓对称，每个 ETF 维护减仓状态：

```python
class SellState:
    def __init__(self, etf):
        self.tier1_sold = False  # > 75% 分位
        self.tier2_sold = False  # > 85% 分位
        self.tier3_sold = False  # > 95% 分位
    
    def reset_all(self):
        """估值回到 < 70% 分位时，所有减仓档位重置"""
        self.tier1_sold = False
        self.tier2_sold = False
        self.tier3_sold = False
```

### 5.5 与定投的联动

**减仓不是孤立动作，需要联动定投规则：**

- PE > 70% 分位（机动定投不投）+ 减仓动作 = **真正降低暴露**
- 否则会出现"一边减仓 + 一边定投买回"的反向操作

**实现：**

```python
def monthly_invest_with_sell_state(etf, pe_percentile, sell_state):
    if sell_state.tier3_sold:
        # 已清仓，进入渐进恢复模式（模块四）
        return progressive_recovery_invest(etf, pe_percentile)
    
    if pe_percentile > 0.70:
        # 机动部分不投这个 ETF（钱进子弹池）
        return only_must_invest(etf)
    
    # 正常机动定投
    return normal_flexible_invest(etf)
```

---

## 6. 模块四：清仓后渐进恢复

### 6.1 触发条件

某 ETF 的 `tier3_sold = True`（已通过三档减仓清仓）。

### 6.2 渐进恢复阶梯

```python
def progressive_recovery_invest(etf, pe_percentile, must_amount, flex_amount):
    """
    清仓后的特殊定投规则
    """
    if pe_percentile >= 0.70:
        # 还在偏高区，完全不投
        return 0
    
    elif pe_percentile >= 0.50:
        # 一阶恢复：只恢复必投部分
        return must_amount * CORE_TARGET_ALLOCATION[etf]
    
    elif pe_percentile >= 0.40:
        # 二阶恢复：必投 + 机动都恢复
        return (must_amount + flex_amount) * CORE_TARGET_ALLOCATION[etf]
    
    else:
        # 三阶恢复：触发加仓档位（< 40%），重置所有清仓状态
        sell_state[etf].reset_all()
        bullet_state[etf].reset_all()
        return trigger_bullet_release(etf, pe_percentile)
```

### 6.3 阶梯逻辑解释

| 阶段 | PE 分位 | 行为 | 理由 |
|------|--------|------|------|
| 完全休眠 | ≥ 70% | 不投 | 清仓后还在偏高区，等深度回调 |
| 一阶恢复 | 50-70% | 必投部分恢复 | 试探性建仓，5000 元的小步进 |
| 二阶恢复 | 40-50% | 机动部分也恢复 | 进入正常定投节奏 |
| 三阶恢复 | < 40% | 触发加仓 + 重置状态 | 进入新一轮加仓周期 |

---

## 7. 模块五：年度再平衡

### 7.1 触发时机

每年 1 月第一个交易日（或最近 1 周内）。

### 7.2 执行流程

```python
def annual_rebalance():
    # Step 1: 计算偏离度
    deviations = {}
    for etf in CORE_ETFS:
        target = CORE_TARGET_ALLOCATION[etf]
        actual = current_holdings[etf] / total_core_value
        deviations[etf] = actual - target  # 正 = 超配，负 = 低配
    
    # Step 2: 判断处理强度
    max_deviation = max(abs(d) for d in deviations.values())
    
    if max_deviation > 0.10:
        return strict_rebalance(deviations)
    elif max_deviation > 0.05:
        return valuation_aware_rebalance(deviations)
    else:
        return None  # 偏离 < 5%，不动
```

### 7.3 强制平衡（偏离 > 10%）

```python
def strict_rebalance(deviations):
    """
    偏离过大，必须执行（防止集中度风险）
    但仍优先用新增定投替代卖出
    """
    overweighted = [etf for etf, d in deviations.items() if d > 0]
    underweighted = [etf for etf, d in deviations.items() if d < 0]
    
    # 检查能否用未来 6 个月定投补足低配
    expected_future_invest = MONTHLY_CASH_FLOW * 6
    needed_to_underweighted = sum(abs(deviations[etf]) * total_core_value 
                                   for etf in underweighted)
    
    if needed_to_underweighted <= expected_future_invest * 0.5:
        # 用定投倾斜补足，不卖出
        adjust_future_invest_ratio(underweighted, weight=2.0)
        return "defer_to_invest"
    
    # 否则执行真实卖出
    for etf in overweighted:
        sell_amount = deviations[etf] * total_core_value
        execute_sell(etf, sell_amount)
    
    for etf in underweighted:
        buy_amount = abs(deviations[etf]) * total_core_value
        execute_buy(etf, buy_amount)
```

### 7.4 估值感知平衡（偏离 5-10%）

```python
def valuation_aware_rebalance(deviations):
    """
    偏离适中，结合估值决策
    """
    for etf, d in deviations.items():
        if d > 0.05:  # 超配
            pe_pct = pe_percentiles[etf]
            if pe_pct > 0.70:
                # 超配 + 偏高 → 卖出超配部分
                execute_sell(etf, d * total_core_value)
            elif pe_pct > 0.50:
                # 超配 + 中性 → 只卖一半
                execute_sell(etf, d * total_core_value * 0.5)
            else:
                # 超配 + 偏低 → 不卖（让赢家飞）
                pass
        
        elif d < -0.05:  # 低配
            pe_pct = pe_percentiles[etf]
            if pe_pct < 0.30:
                # 低配 + 偏低 → 加仓补足
                execute_buy(etf, abs(d) * total_core_value)
            elif pe_pct < 0.50:
                # 低配 + 中性 → 部分补足
                execute_buy(etf, abs(d) * total_core_value * 0.5)
            else:
                # 低配 + 偏高 → 不买（用未来定投慢慢平衡）
                pass
```

### 7.5 优先级原则

**"用新增定投替代卖出" > "真实卖出"**

- 偏离不大时，调整未来 6 个月的定投比例倾斜
- 只有偏离极大或时间紧迫时才真实卖出
- 这样既再平衡又避免税费/心理成本

---

## 8. 数据需求

### 8.1 必需的数据源

| 数据 | 来源 | 更新频率 | 用途 |
|------|------|---------|------|
| 4 个 ETF 的当前 PE | akshare / 理杏仁 | 日级 | 估值判断 |
| 4 个 ETF 的 PE 历史分位（10 年） | akshare / 理杏仁 | 月级 | 触发档位计算 |
| 黄金价格历史（10 年） | akshare | 日级 | 黄金估值替代 |
| 4 个 ETF 的当前持仓数据 | 用户手动输入 / broker API | 月级 | 计算偏离度 |

### 8.2 数据存储

```
data/core_portfolio/
├── valuations/
│   ├── 纳指100_pe_history.csv     # 10 年 PE 时间序列
│   ├── 沪深300_pe_history.csv
│   ├── 低波红利_pe_history.csv
│   └── 黄金_price_history.csv
├── holdings/
│   └── 2026-05.json                # 月度持仓快照
├── states/
│   ├── bullet_state.json           # 子弹池 + 释放状态
│   └── sell_state.json             # 减仓状态
└── transactions/
    └── 2026-05.json                # 当月所有交易记录
```

### 8.3 状态文件示例

```json
// bullet_state.json
{
  "updated_at": "2026-05-25",
  "pools": {
    "纳指100": 8500.0,
    "黄金": 6200.0,
    "低波红利": 11250.0,
    "沪深300": 11250.0
  },
  "tier_released": {
    "纳指100": {"t1": false, "t2": false, "t3": false},
    "黄金": {"t1": false, "t2": false, "t3": false},
    "低波红利": {"t1": false, "t2": false, "t3": false},
    "沪深300": {"t1": true, "t2": false, "t3": false}
  },
  "total": 37200.0,
  "max_total": 45000.0,
  "force_release_due": false
}
```

---

## 9. 实现路径（首版交付范围）

### 9.1 范围内（V1）

- [ ] 数据获取层：从 akshare 拉取 4 个 ETF 的 PE 历史，计算分位数
- [ ] 月度定投计算器：输入 PE 分位 + 当前持仓，输出本月分配方案
- [ ] 子弹池状态管理：积累 / 释放 / 强制释放逻辑
- [ ] 减仓信号生成：PE 分位触发，输出建议卖出方案
- [ ] 渐进恢复逻辑：清仓后的特殊处理
- [ ] 年度再平衡报告：1 月触发，输出调整方案
- [ ] 命令行工具：每月运行一次，输出操作建议（不自动下单）

### 9.2 范围外（明确剔除）

- ❌ 自动下单（需人工确认后手动执行）
- ❌ 卫星仓的任何修改
- ❌ 前端界面（先做 CLI，后续再说）
- ❌ 邮件通知（可在 V2 接入现有 advisor 系统）
- ❌ 回测验证（数据获取层完成后单独做）

### 9.3 与现有系统的关系

- 数据层：复用 `api/data_fetcher` 的 akshare 调用模式
- 文件结构：新增 `api/core_portfolio/` 模块，独立于 `api/strategy/`
- 配置：新增 `config/core_portfolio.yaml`
- CLI：新增 `tests/core_portfolio_advisor.py` 月度运行脚本

---

## 10. 测试与验证

### 10.1 单元测试

- `test_valuation_percentile.py`：分位数计算正确性
- `test_monthly_invest.py`：定投分配逻辑（覆盖低/中/高估三种场景）
- `test_bullet_pool.py`：子弹积累 + 释放 + 强制释放
- `test_sell_rules.py`：减仓三档触发
- `test_progressive_recovery.py`：清仓后恢复阶梯
- `test_annual_rebalance.py`：再平衡决策矩阵

### 10.2 集成测试（历史回测）

用 2015-2024 年数据回测整套规则：

- 总收益 vs 基准（4 ETF 等比例无脑定投）
- 最大回撤
- 子弹释放次数（验证三档分位是否合理）
- 减仓次数（验证 75/85/95 是否合理）
- 年度再平衡次数

**验收标准：**
- 总收益 ≥ 基准
- 最大回撤 ≤ 基准
- 子弹释放 3-5 年内至少触发一档 1 次

### 10.3 实盘验证（V1 后）

首月人工对照：
- 系统生成本月建议
- 人工独立计算一遍
- 对比差异，定位 bug

---

## 11. 风险与限制

### 11.1 数据风险

- **PE 分位数依赖历史数据完整性**：如果数据源缺失或错误，触发条件会失真
- **缓解**：数据获取层加完整性校验，缺失数据时报错而非默认值

### 11.2 模型风险

- **历史分位数 ≠ 未来分位数**：极端情况下（结构性牛市/熊市），分位数会持续偏高/偏低，规则可能失效
- **缓解**：年度再平衡时人工复核规则参数，必要时调整阈值

### 11.3 执行风险

- **心理障碍**：减仓比加仓难执行，容易"再等等"
- **缓解**：
  - 系统每月自动生成建议邮件
  - 与配偶/朋友约定监督机制
  - 提前写好"减仓剧本"，到时候无脑执行

### 11.4 黄金估值替代风险

- **金价分位数 ≠ 真实估值**：黄金没有现金流，估值逻辑与股票指数不同
- **缓解**：V1 用价格分位数，V2 引入金银比/实际利率等更精细指标

---

## 12. 后续演进（参考，不做）

- **V2**：邮件通知 + 前端报表
- **V3**：黄金估值用金银比 + 实际利率组合指标
- **V4**：引入宏观情绪指标（如 VIX、A 股成交量）作为辅助信号
- **V5**：自动下单（券商 API 集成）

---

## 附录 A：完整规则速查表

### 月度定投
```
现金流 1W → 必投 5K（无脑按目标比例）+ 机动 5K（看估值）
机动权重：< 30% 分位 1.5x，30-70% 1.0x，70-90% 0.5x，> 90% 0x（攒子弹）
```

### 加仓子弹
```
上限：9 个月 = 4.5W（按目标比例分仓）
触发：单 ETF
  PE < 40% → 打 1/3
  PE < 25% → 再打 1/3
  PE < 15% → 打最后 1/3
强制释放：满 9 个月，季度检查时按估值最低标的释放
```

### 减仓
```
触发：单 ETF
  PE > 75% → 卖 1/3 → 100% 现金流
  PE > 85% → 再卖 1/3 → 50% 现金流 + 50% 安全资产
  PE > 95% → 卖最后 1/3 → 100% 安全资产
```

### 清仓后恢复
```
PE ≥ 70% → 不投
PE 50-70% → 恢复必投
PE 40-50% → 恢复机动
PE < 40% → 触发加仓 + 重置所有状态
```

### 年度再平衡
```
偏离 > 10% → 强制平衡（优先用未来定投倾斜替代卖出）
偏离 5-10% → 估值感知平衡（决策矩阵）
偏离 < 5% → 不动
```

## 附录 B：决策矩阵

### 月度机动定投权重

| PE 分位 | 权重 |
|--------|------|
| < 30% | 1.5x |
| 30-70% | 1.0x |
| 70-90% | 0.5x |
| > 90% | 0x（攒子弹）|

### 加仓三档

| PE 分位 | 动作 |
|--------|------|
| < 40% | 打 1/3 子弹 |
| < 25% | 再打 1/3 |
| < 15% | 打最后 1/3 |

### 减仓三档

| PE 分位 | 动作 | 资金去向 |
|--------|------|---------|
| > 75% | 卖 1/3 持仓 | 100% 现金流 |
| > 85% | 再卖 1/3 | 50% 现金流 + 50% 安全资产 |
| > 95% | 卖最后 1/3 | 100% 安全资产 |

### 年度再平衡决策

| 偏离度 | 处理 |
|--------|------|
| < 5% | 不动 |
| 5-10% | 估值感知（D 矩阵） |
| > 10% | 强制平衡（优先用定投倾斜） |

### 估值感知平衡 D 矩阵（偏离 5-10%）

| 超配标的估值 | 低配标的估值 | 操作 |
|------------|------------|------|
| > 70% | < 50% | 全额平衡 |
| > 70% | > 70% | 只卖不买（钱进现金流） |
| < 50% | < 50% | 只买不卖（从现金流补） |
| < 50% | > 70% | 不动 |
| 中性 | 中性 | 半平衡（只调一半） |
