# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

A 股量化交易平台，包含完整的选股流水线（数据获取 → 筛选 → K线图 → LLM 打分 → 信号生成）和回测引擎。

核心特性：
- 数据源：AkShare（默认，免费）/ BaoStock（备选）
- 策略框架：vnpy 3.9.0 CTA 策略模板
- 交易规则：内置 A 股规则（T+1、涨跌停、100 股最小单位、ST 识别）
- 选股流水线：全市场扫描 → K线图生成 → Claude LLM 两阶段打分 → 买入信号
- 回测：单股回测 + 组合回测（轮动策略）
- 调度：APScheduler 每日 15:30 自动执行完整流水线

## 常用命令

```bash
# 环境准备
pip install -r requirements.txt

# 数据下载（AkShare 默认，可选 --source baostock）
python main.py data --start 2024-01-01 --end 2025-12-31
python main.py data --start 2024-01-01 --end 2025-12-31 --source baostock

# 单股回测
python main.py backtest --strategy b1 --symbol 600000 --start 2024-01-01 --end 2025-06-30

# 参数优化
python main.py optimize --strategy b1 --symbol 600000 --start 2024-01-01 --end 2025-06-30

# 全市场扫描 + K线图生成
python main.py scan --strategy b1 --date 2025-05-15

# LLM 两阶段打分（需要 CLAUDE_API_KEY 环境变量）
python main.py score --date 2025-05-15 --model claude-opus-4-20250514

# 组合回测（轮动策略，最大 10 只持仓）
python main.py portfolio --strategy b1 --start 2024-01-01 --end 2025-06-30

# 生成买入信号（优先使用 LLM 打分结果，否则用筛选结果 TOP 10）
python main.py signal --date 2025-05-15

# 调度器（每日 15:30 自动执行完整流水线）
python main.py scheduler start --strategy b1 --source akshare
python main.py scheduler stop
python main.py scheduler status
```

## 核心架构

### 完整流水线（5 个环节）

```
环节1: 数据获取          环节2: 筛选+可视化       环节3: LLM打分
AkShare API → CSV →    Scanner全市场扫描 →     Claude两阶段打分
vnpy数据库              K线图生成               (100→30→10)
                                              
环节4: 信号生成          环节5: 自动调度
买入信号JSON →          APScheduler每日15:30
T+1开盘执行             自动执行环节1-4
```

### 模块职责

| 模块 | 职责 |
|------|------|
| `fetcher/` | 数据获取（AkShareDataFetcher / BaoStockDataFetcher） |
| `adapter/` | CSV → vnpy BarData 转换，导入 SQLite |
| `api/scanner/` | 全市场策略筛选，输出候选股票 JSON |
| `api/visualizer/` | K线图生成，可扩展面板（TrendLinePanel, KDJPanel） |
| `llm_scorer/` | Claude API 两阶段打分（表格筛选 + 图片精选） |
| `indicator/` | 技术指标纯函数（KDJ、知行趋势、振幅） |
| `strategy/` | vnpy CTA 策略（BaseStrategy + B1Strategy） |
| `backtest/` | 单股回测引擎 + 报告生成 |
| `portfolio/` | 组合回测（轮动策略，T日收盘信号→T+1开盘执行） |
| `scheduler/` | APScheduler 定时任务，PID 管理，日志 |
| `config/` | 全局配置（费率、路径、回测参数） |

### 关键设计决策

**股票代码格式**
- AkShare/内部标识：6 位纯数字（`600000`）
- BaoStock：`sh.600000` / `sz.000001`
- vnpy：`600000.SSE` / `000001.SZSE`
- 转换函数：`utils.utils._normalize_stock_code()` / `_convert_stock_code()`

**A 股交易规则（BaseStrategy 内置）**
- T+1：`buy_date` 字段 + `can_sell` 标志位
- 涨跌停：主板 ±10%，创业板/科创板（30/68 开头）±20%，ST ±5%
- 最小单位：`buy_stock()` / `sell_stock()` 自动 100 股取整

**指标桥接**
- vnpy `ArrayManager`（numpy）→ `IndicatorCalculator` → pandas DataFrame → 指标纯函数
- 策略中通过 `self.indicator.kdj()` / `zx_trend()` / `amplitude()` 调用

**LLM 打分流程**
- Stage 1：候选股票表格（Markdown）→ Claude → TOP 30
- Stage 2：K线图片（2 批 × 15 张）→ Claude → TOP 10
- Fallback：API 失败时使用指标排序兜底

**组合回测**
- T 日收盘生成信号，T+1 开盘价执行
- 等权分配，最大 10 只持仓
- 完整费用计算：佣金 + 印花税 + 过户费 + 滑点

## 添加新策略

1. 在 `strategy/` 创建文件，继承 `BaseStrategy`
2. 实现 `execute_logic(bar, can_sell, at_upper_limit, at_lower_limit)` 方法
3. 在 `main.py` 的 `strategy_map` 中注册

关键约束：
- 参数必须在 `parameters` 列表中声明才能用于优化
- 使用 `self.buy_stock()` / `self.sell_stock()`（自动处理 100 股取整）
- 必须检查 `can_sell`（T+1）和涨跌停标志位

## 添加新指标

1. 在 `indicator/indicators.py` 添加纯函数（接受 DataFrame，返回 Series）
2. 在 `IndicatorCalculator` 添加桥接方法
3. 在策略中通过 `self.indicator.xxx()` 调用

## 输出目录结构

```
output/
├── candidates/    # 筛选结果 JSON（candidates_YYYYMMDD.json）
├── charts/        # K线图 PNG
├── scores/        # LLM 打分结果 JSON
├── signals/       # 买入信号 JSON（buy_YYYYMMDD.json）
└── portfolio/     # 组合回测结果 JSON + PNG
reports/           # 单股回测报告 PNG
logs/              # 调度器日志
```

## 注意事项

- 首次使用必须运行 `python main.py data` 下载数据
- AkShare 请求间隔 0.3s 防限流，全市场下载耗时较长
- LLM 打分需要 `CLAUDE_API_KEY` 环境变量
- 调度器通过 PID 文件管理进程（`logs/scheduler.pid`）
- 回测周期建议至少 6 个月
- 参数优化容易过拟合，需样本外验证
- 仅支持日线级别回测
- 无测试框架、无 CI/CD
