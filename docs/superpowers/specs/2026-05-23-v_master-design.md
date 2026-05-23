# v_master 策略设计稿

- 日期：2026-05-23
- 作者：cola1213
- 状态：draft → 待审阅

## 1. 背景与目标

A 股盘面里，"底部巨量阳线 + 洗盘 + 二次放量启动"通常被视为主力建仓后启动的痕迹。
B1 抓的是已经在上方运行、回踩黄线企稳的"建仓尾声"，而 v_master 想抓更左侧的一段：
**下跌末端的巨量启动日（"V 锚"）→ 短期洗盘不破低 → 二次放量阳确认主力还在 → 入场**。

设计目标：

- 信号锐利、可解释，规则少而硬
- 卖出极简：跌破 V 锚低点即清仓，对应"主力出走"的硬假设
- 与 B1 完全独立，不耦合
- 复用现有 `BaseStrategy` 的 A 股交易规则与撮合机制

## 2. 架构定位

新增策略 + 新增扫描脚本 + 注册到回测服务。沿用 B1 同款骨架。

### 2.1 文件清单

| 路径 | 类型 | 用途 |
|------|------|------|
| `api/strategy/v_master.py` | 新增 | `VMasterStrategy`（继承 `BaseStrategy`）|
| `api/strategy/__init__.py` | 修改 | 导出 `VMasterStrategy` |
| `tests/scan_v_master_full.py` | 新增 | 全市场扫描器，写入 `selected/{date}/v_master.json` |
| `api/services/backtest_service.py` | 修改 | `STRATEGY_REGISTRY` 注册 `"v_master"` |

不动：`BaseStrategy`、`indicator/`、`patterns.py`、scanner、portfolio_service。

### 2.2 不复用 / 不继承 B1 的原因

- 信号语境不同：B1 关注"已在大哥黄之上、回踩企稳"；v_master 关注"还在下跌区、第一根放量阳"
- 卖出逻辑差异巨大：B1 三层卖出 + 放飞减仓；v_master 单条铁律
- 把 v_master 写成 B1 子类会污染 B1 类属性表，得不偿失

## 3. 信号定义

记当前 bar 索引为 `T`，候选索引为 `i`。

### 3.1 巨量基础日 V_idx（V 锚）

在 `[T - cooldown_max, T - cooldown_min]` 窗口内，且 `i ≥ lookback_v 的下界`，扫描每个 i，找最早一个满足如下条件的索引：

- **下跌语境**：`closes[i] ≤ max(highs[i-60..i-1]) × 0.80`（近 60 日高点之下跌幅 ≥ 20%）
- **阳线**：`closes[i] > opens[i]` 且 `(closes[i]-opens[i])/opens[i]*100 ≥ v_body_min_pct`
- **巨量**：`volumes[i] / mean(volumes[i-5..i-1]) ≥ v_vol_ratio`
- **不能涨停**：当日涨幅 < 板块涨停限制 - 0.1（避开一字板）

参数默认值：

| 参数 | 默认 | 说明 |
|------|------|------|
| `lookback_v` | 60 | 往回最多看多少日找 V |
| `cooldown_min` | 5 | V 与 T 至少间隔交易日 |
| `cooldown_max` | 15 | V 与 T 最多间隔交易日 |
| `down_lookback` | 60 | 下跌语境的高点回看天数 |
| `down_drawdown` | 20.0 | 跌幅阈值（%） |
| `v_body_min_pct` | 3.0 | 主板阳线最小实体涨幅；30/68 用 4.0 |
| `v_vol_ratio` | 3.0 | V 锚量比阈值（基准 5 日均量） |

### 3.2 洗盘期约束（V_idx+1 … T-1）

- **不破巨量低点（铁律）**：`min(lows[V_idx+1 .. T-1]) ≥ lows[V_idx]`
- **无放量大阴**：洗盘期任一 j，若 `(opens[j]-closes[j])/opens[j]*100 > 5.0%` 且 `volumes[j]/mean(volumes[j-5..j-1]) > 1.5` → 整票淘汰

### 3.3 决策日 T（二次启动确认）

T 当日同时满足：

- **阳线**：`closes[T] > opens[T]`，涨幅 ≥ `t_body_min_pct`（主板 2.0%；30/68 2.5%）
- **温和放量**：`volumes[T] / mean(volumes[T-5..T-1]) ≥ t_vol_ratio`（默认 1.5）
- **站上短期均线**：`closes[T] ≥ MA5[T]`
- **量能重心上移**：`mean(volumes[T-4..T]) > mean(volumes[V_idx-20..V_idx-1])`
- **均线翻多**：`MA10[T] > MA20[T]` 且 `MA10[T] > MA10[T-1]`（拐头向上）
- **当日不能涨停**

### 3.4 入场前置过滤

- 翻番过滤：近 60 日 max/min ≥ 1.8 跳过
- 涨停 / 一字板跳过
- ST / 板块涨跌停限制走 `BaseStrategy._get_limit_rate()`

### 3.5 满仓买入

满足全部条件 → `buy_full(bar.close_price, reason)`，`reason` 形如：
`"v_master[V=2026-05-12 V量比3.6 量重移1.4x]"`。

按 `BaseStrategy` 的 T 日下单 / T+1 区间撮合规则成交。

### 3.6 卖出规则（仅一条）

`bar.close_price < v_low` → 全仓清出，`reason = f"破V锚低点{v_low:.2f}"`。

无放飞减仓、无回撤止盈、无时间止损。

## 4. 状态机

### 4.1 实例字段

```
v_low: float = 0.0       # V 锚日的最低价，整笔交易锁定
v_idx_date: str = ""     # V 锚日期字符串，用于 reason 与复盘
buy_price: float = 0.0   # 与 B1 一致用法
```

不再维护 `hold_days / max_profit_pct / scale_stage / below_yellow_count` 等。

### 4.2 单 bar 流程

```
on_bar → BaseStrategy 完成 am 更新、涨跌停判定、T+1 判定 → execute_logic

execute_logic:
  if pos > 0:
    if can_sell and not at_lower_limit:
      if bar.close < v_low:
        sell_stock(... reason="破V锚低点{v_low:.2f}")
    return

  if pos == 0:
    if at_upper_limit: return
    if 翻番过滤: return
    V_idx = find_v_anchor(am)
    if V_idx is None: return
    if not check_washout(am, V_idx): return
    if not check_today_confirm(am, V_idx): return
    buy_full(bar.close, reason)
    # buy_price / v_low / v_idx_date 在 on_trade 成交回调中设置
```

### 4.3 状态写入时机

- `v_low / v_idx_date / buy_price` **仅在 `on_trade` 成交回调里**写入；`buy_full` 只是排队下单。
  避免 T+1 撮合失败但状态被错误标记的问题。
- `on_trade` 卖出回调：`v_low=0.0`, `v_idx_date=""`, `buy_price=0.0`。

## 5. 数据流与扫描器

### 5.1 数据来源

全部从 `self.am`：`open_array / close_array / high_array / low_array / volume_array`。
`am.size = 200`（继承）。本设计需要的最深 lookback：

- `lookback_v = 60`
- V 之前 20 日量基线 → 80
- 翻番 60 日 → 取并集仍是 80 内

`load_bar(350)` 自然日 ≈ 226 交易日，预热充足。

### 5.2 扫描器结构

`tests/scan_v_master_full.py`，与 `scan_b1_full.py` 同构：

- 读 `data/{symbol}.csv` → numpy
- 调用 `VMasterStrategy._find_v_anchor / _check_washout / _check_today_confirm`（`@staticmethod` 抽出供扫描器复用）
- `ProcessPoolExecutor`，默认 `--workers 4`
- 命中即写 `selected/{yyyy-mm-dd}/v_master.json`

### 5.3 输出 schema

```json
{
  "scan_date": "2026-05-23",
  "strategy": "v_master",
  "total_scanned": 5400,
  "candidates_count": 12,
  "candidates": [
    {
      "symbol": "600000",
      "name": "浦发银行",
      "match_date": "2026-05-23",
      "close": 8.42,
      "v_idx_date": "2026-05-12",
      "v_low": 8.05,
      "v_vol_ratio": 3.6,
      "today_vol_ratio": 1.8,
      "indicators": {"ma5": 8.30, "ma10": 8.21, "ma20": 8.15}
    }
  ]
}
```

候选按 `v_vol_ratio` 倒序（不引入打分概念）。

## 6. 错误处理与边界

| 场景 | 处理 |
|------|------|
| `n_total < lookback_v + 25` | 不入场 |
| 60 日窗口在数据起点不足 | 用现有数据最大值，不报错 |
| 量基线 i < 5 | 该 i 不当候选 |
| `opens[i] ≤ 0` 或 `closes[i] ≤ 0` | 跳过该 i |
| 当日涨停（≥ 限制 - 0.1） | 不当 V 锚也不当决策日 |
| ST / 板块涨跌停 | 走 `_get_limit_rate()` |
| T+1 撮合失败 | `_cross_pending_buy` 自动放弃；状态字段不写 |
| 持仓中再次扫到信号 | `pos > 0` 直接 return，不重复入场 |
| 卖出回调 | 重置 `v_low / v_idx_date / buy_price` |

## 7. 测试与验证

### 7.1 单股冒烟

挑 2~3 只历史上明显有"底部巨量→洗盘→二次启动"形态的票（如医药/科技板块阶段底股票），跑单股回测，验收：

- 至少有 1 个 buy/sell 配对
- 卖出 reason 全为 `"破V锚低点..."` 或回测结束强平
- 买入 reason 含 V 锚日期，对照 K 线图肉眼可验证

### 7.2 全市场扫描

跑两个日期：

```bash
python tests/scan_v_master_full.py 2026-05-23 --workers 8
python tests/scan_v_master_full.py 2024-09-30 --workers 8
```

验收：
- 不报错，输出 `selected/{date}/v_master.json`
- 候选数 5~50（过多说明阈值松，过少说明严）
- 抽 3 只肉眼对照 K 线

### 7.3 回归

跑一遍 B1 single 回测，确认 STRATEGY_REGISTRY 改动没破坏 B1。

### 7.4 不做的事

- 不做参数扫描（首版交付后另起）
- 不做组合回测（首版交付后另起）
- 不接 advisor / 邮件 / 前端

## 8. 不在范围内（明确剔除）

- LLM 打分接入
- 多因子加分体系（B1 风格）
- 放飞减仓 / 回撤止盈 / 时间止损
- OBV / CMF 等新增指标
- 板块过滤、热点叠加
- 调度器自动跑

## 9. 后续演进（参考，不做）

- 参数扫描（环境变量覆盖类属性，复用 B1 的 `_apply_*_env_overrides` 模式）
- 组合层接入：复用 `portfolio_b1_small.py` 改 portfolio_v_master
- 卖出端补充：破 V 后允许小幅缓冲（避免插针出局）
- 二次启动确认增加换手率维度
