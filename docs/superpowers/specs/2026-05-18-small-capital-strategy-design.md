# 小资金策略设计文档（稳健累积型）

## 1. 背景与目标

### 问题
现有 B1 Top-2 策略在 100w 资金下表现良好（年化 15.84%，最大回撤 -13.06%），但在 20w 小资金下表现不佳。原因：
- 单只 50% 仓位（10w）对小资金过于集中
- 高价股（>50 元）买入股数太少，交易不灵活
- 回撤控制不足，连续亏损打击信心

### 目标
- **初始资金**：20w
- **最大回撤**：< 10%
- **年化收益**：8-12%（稳健为主）
- **交易限制**：仅主板（600/00 开头），新手账户可交易
- **核心理念**：通过小盈利累积正反馈，严格止损避免连续亏损

## 2. 选股规则

### 硬过滤条件
1. **代码前缀**：600/000/001（排除创业板 30、科创板 68、北交所 8 开头）
2. **价格限制**：≤ 50 元（避免买不起或股数太少影响交易灵活性）
3. **ST 股票**：排除（风险高且有特殊涨跌停限制）
4. **流动性**：日成交额 > 5000 万（保证能顺利买卖）

### 评分逻辑
- 复用现有 B1 策略扫描逻辑（`tests/scan_v2_style.py`）
- 技术指标：KDJ + 知行趋势 + 振幅
- 每日扫描全市场，取 TOP 3 候选

## 3. 仓位管理

### 市场状态判断
**强市条件**（同时满足）：
- 大盘收盘价 ≥ 大哥黄（30 日双均线）
- 大哥黄 5 日斜率 > 0（趋势向上）

**弱市条件**：
- 大盘收盘价 < 大哥黄

### 持仓槽位与单只仓位
| 市场状态 | 最大持仓数 | 单只仓位 | 说明 |
|---------|-----------|---------|------|
| 强市 | 3 只 | 35% | 20w × 35% = 7w/只 |
| 弱市 | 1 只 | 40% | 20w × 40% = 8w/只 |

### 买入时机与限制
1. **时机**：T 日收盘扫描，T+1 开盘买入（滑点 +0.1%）
2. **大盘过滤**：大盘收盘 < 大哥黄时禁止买入
3. **冷却机制**：连续 2 笔全清亏损后，冷却 10 个交易日不买入

## 4. 卖出规则（6 类，按优先级）

### 4.1 硬止损（优先级最高）
- **弱市**：亏损 ≤ -3% 全清
- **强市**：亏损 ≤ -5% 全清
- **Why**：小资金承受不起大回撤，快速止血保护本金

### 4.2 趋势止损
1. **跌破大哥黄**：收盘价 < 大哥黄，次日开盘全清
2. **破趋势白（曾上穿）**：曾站上趋势白（10 日双均线）后再跌破，次日开盘全清

### 4.3 形态止损
- **阴线放量**：量比 > 1.5 且当日跌幅 > 5%，次日开盘全清
- **Why**：主力出货信号

### 4.4 时间止损
- **T+5 不涨即卖**：持仓 5 个交易日且累计涨幅 < 2%，次日开盘全清
- **Why**：避免资金长期占用在弱势股上

### 4.5 分批止盈
- **规则**：每涨 8% 卖出剩余仓位的 1/3
- **止盈档位**：+8%（卖 1/3）、+16%（再卖 1/3）、+24%（再卖 1/3）
- **Why**：锁定利润同时保留上涨空间

### 4.6 卖出执行
- **时机**：T 日收盘判断信号，T+1 开盘卖出（滑点 -0.1%）
- **分批处理**：止盈按 1/3 比例卖出，其他情况全清
- **不足 100 股**：按全清处理（A 股最小交易单位）

## 5. 技术实现

### 5.1 文件结构
```
tests/
  portfolio_small_capital.py    # 新建：小资金组合回测主程序
  scan_v2_style.py              # 复用：扫描逻辑
api/
  portfolio/rules.py            # 复用：大哥黄/趋势白计算
  config/settings.py            # 复用：费用配置
```

### 5.2 关键修改点（相对 portfolio_b1_top2.py）

**1. 选股过滤（scan_v2_style.py 或 portfolio_small_capital.py）**
```python
# 添加过滤条件
def filter_for_small_capital(symbol: str, bar: pd.Series) -> bool:
    # 代码前缀：600/000/001
    if not (symbol.startswith('600') or symbol.startswith('000') or symbol.startswith('001')):
        return False
    # 价格 ≤ 50 元
    if bar['close'] > 50:
        return False
    # 排除 ST（从 stock_extra_info.json 读取）
    # 成交额 > 5000 万
    if bar['volume'] * bar['close'] < 50_000_000:
        return False
    return True
```

**2. 仓位计算**
```python
# 强市：最多 3 只，单只 35%
# 弱市：最多 1 只，单只 40%
max_slots = 3 if market_strong else 1
per_pos_pct = 0.35 if market_strong else 0.40
per_pos_cap = capital * per_pos_pct
```

**3. 止损阈值**
```python
# 硬止损
stop_pct = -5.0 if market_strong else -3.0
if cur_profit <= stop_pct:
    return f"硬止损({stop_pct:.0f}%)", 1.0
```

**4. 时间止盈参数**
```python
T5_HOLD_DAYS = 5
T5_MIN_GAIN_PCT = 2.0

if pos.hold_days >= T5_HOLD_DAYS and cur_profit < T5_MIN_GAIN_PCT:
    return f"T+{T5_HOLD_DAYS} 涨幅<{T5_MIN_GAIN_PCT}%", 1.0
```

**5. 分批止盈档位**
```python
TP_LEVELS = [8, 16, 24]  # 每涨 8% 一档
TP_RATIO = 1.0 / 3.0     # 每次卖 1/3
```

**6. 冷却机制**
```python
# 连续 2 笔全清亏损后冷却 10 日
cooldown_loss_streak = 2
cooldown_offset = 10
```

### 5.3 回测参数
```python
python tests/portfolio_small_capital.py \
  --start 2025-01-01 \
  --end 2026-05-17 \
  --capital 200000 \
  --workers 8
```

## 6. 预期效果与对比

### 预期指标
| 指标 | 小资金策略（20w） | B1 Top-2（100w） |
|------|------------------|------------------|
| 年化收益 | 8-12% | 15.84% |
| 最大回撤 | < 10% | -13.06% |
| 胜率 | > 60% | 61.25% |
| 交易频率 | 中等（T+5 止损） | 较高（T+3 止损） |
| 风险等级 | 低 | 中 |

### 设计权衡
**为什么收益预期更低？**
- 更严格的止损（-3%/-5% vs -4%/-7%）会提前止损部分反弹股
- 仅主板股票，排除了创业板/科创板的高成长机会
- 价格 ≤ 50 元过滤掉部分优质高价股

**为什么更适合小资金？**
- 回撤控制更严格，避免连续亏损打击信心
- 2-3 只持仓平衡了分散和集中（20w ÷ 3 ≈ 6.7w/只，买 50 元股票可买 1300 股）
- 主板股票流动性好，新手账户可交易

## 7. 风险与限制

### 已知风险
1. **过度止损**：-3% 硬止损可能在震荡市中频繁止损
2. **错过大行情**：T+5 时间止损可能提前卖出强势股
3. **样本偏差**：仅主板股票，可能错过小盘成长股机会

### 后续优化方向
1. **动态止损**：根据波动率调整止损阈值
2. **分批建仓**：首次买入 50%，突破后加仓 50%
3. **行业轮动**：避免 3 只持仓集中在同一行业

## 8. 实施计划

### Phase 1：代码实现（1-2 天）
1. 复制 `portfolio_b1_top2.py` → `portfolio_small_capital.py`
2. 修改选股过滤、仓位计算、止损止盈参数
3. 添加价格/代码前缀/ST 过滤逻辑

### Phase 2：回测验证（1 天）
1. 运行 2025-01-01 ~ 2026-05-17 回测
2. 对比 20w 和 100w 资金下的表现差异
3. 分析交易明细，识别问题交易

### Phase 3：参数调优（可选）
1. 如果回撤 > 10%，收紧止损或减少持仓数
2. 如果收益 < 5%，放宽时间止损或提高止盈档位
3. 如果胜率 < 55%，优化选股逻辑

## 9. 附录：关键代码片段

### 市场状态判断（复用现有逻辑）
```python
def market_is_strong(date: str, symbol: str, index_dfs: dict) -> bool:
    idx = index_dfs[pick_index_for(symbol)]
    hist = get_history_until(idx, date)
    closes = hist['close'].values.astype(float)
    yellow = _yellow_series(closes)
    cond_close = float(closes[-1]) >= float(yellow[-1])
    slope_5 = (float(yellow[-1]) / float(yellow[-6])) - 1 if len(yellow) >= 6 else 0.0
    return cond_close and slope_5 > 0
```

### 卖出信号计算（修改版）
```python
def calc_sell_signal(pos: Position, df: pd.DataFrame, date: str, market_strong: bool):
    # 0. 硬止损
    stop_pct = -5.0 if market_strong else -3.0
    if cur_profit <= stop_pct:
        return f"硬止损({stop_pct:.0f}%)", 1.0
    
    # 1. 跌破大哥黄
    if cur_close < cur_yellow:
        return "跌破大哥黄", 1.0
    
    # 2. 阴线放量
    if vol_r > 1.5 and drop_pct > 5.0:
        return f"阴线放量", 1.0
    
    # 3. 破趋势白（曾上穿）
    if pos.above_white_once and cur_close < cur_white:
        return "破趋势白", 1.0
    
    # 4. T+5 不涨即卖
    if pos.hold_days >= 5 and cur_profit < 2.0:
        return f"T+5 涨幅<2%", 1.0
    
    # 5. 分批止盈（8%/16%/24%）
    TP_LEVELS = [8, 16, 24]
    next_lv = pos.tp_level_done + 1
    if next_lv <= len(TP_LEVELS) and cur_profit >= TP_LEVELS[next_lv - 1]:
        pos.tp_level_done = next_lv
        return f"分批止盈+{TP_LEVELS[next_lv-1]}%", 1.0/3.0
    
    return None, 0.0
```
