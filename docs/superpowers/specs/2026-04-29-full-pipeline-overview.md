# A 股量化交易全流程系统 — 概要设计

## 1. 项目目标

在现有 vnpy 回测框架基础上，构建一套完整的 A 股量化交易流程系统：

1. **自动数据拉取**：每个交易日收盘后自动拉取全市场最新数据
2. **策略批量筛选**：对全市场 5000+ 只 A 股进行策略条件扫描
3. **LLM 智能打分**：两阶段筛选（表格初筛 + 图形精筛），由 Claude Opus 4.7 对候选股票进行打分、分析和排序
4. **组合回测**：将筛选结果作为组合进行历史回测，验证策略有效性
5. **交易信号生成**：生成买入/卖出信号（分阶段实现：先手动执行，后续对接券商 API）

## 2. 架构选型

**单体流水线架构**：在现有代码库上扩展，新增 5 个模块。

选择理由：
- 每日一次扫描，不需要高并发
- 现有代码库完善，复用度高
- 快速验证，2-3 周可上线
- 后期可用 multiprocessing 优化性能，无需重构

## 3. 定时任务策略

**收盘后统一处理，次日开盘执行。**

| 时间 | 操作 | 说明 |
|------|------|------|
| T 日 15:30 | 拉取全市场收盘数据 | 增量更新 |
| T 日 15:35 | 检查持仓 → 生成卖出信号 | 基于 T 日收盘数据 |
| T 日 15:40 | 全市场扫描筛选 | 约 15-20 分钟 |
| T 日 16:00 | 生成 K 线图 + LLM 两阶段打分 | 约 3-4 分钟 |
| T 日 16:15 | 生成买入信号 | |
| T+1 日 9:30 | 开盘，执行买卖信号 | 先手动，后续对接券商 API |

选择理由：
- 数据完整性：使用收盘数据，无需处理盘中数据源
- 逻辑简洁：单一数据源（BaoStock），无需集成多个 API
- 符合 T+1 规则：T 日买入 T+1 日卖出，与 A 股规则一致
- 成本可控：BaoStock 免费且稳定

## 4. 模块划分

**现有模块（复用）：**
- `fetcher/` - 数据获取（BaoStock）
- `adapter/` - 数据适配（CSV → vnpy DB）
- `strategy/` - 策略定义
- `indicator/` - 技术指标计算
- `backtest/` - 单股回测引擎

**新增模块：**
- `scanner/` - 批量筛选引擎
- `visualizer/` - K 线图生成（可扩展副图系统）
- `llm_scorer/` - LLM 两阶段打分
- `portfolio/` - 组合回测
- `scheduler/` - 定时任务调度

## 5. 数据流水线

```
BaoStock API → CSV 文件 → vnpy 数据库
                                ↓
                        Scanner 全市场筛选
                                ↓
                          候选股票池（~100只）
                                ↓
                    ┌───────────┴───────────┐
                    ↓                       ↓
            Visualizer K线图生成     汇总表格生成
                    ↓                       ↓
                    └───────────┬───────────┘
                                ↓
                    LLM 两阶段打分（表格初筛 → 图形精筛）
                                ↓
                          TOP 10 + 详细分析
                                ↓
                    ┌───────────┴───────────┐
                    ↓                       ↓
            交易信号生成            Portfolio 组合回测
                    ↓                       ↓
            buy/sell JSON              回测报告
```

## 6. 目录结构（新增部分）

```
stock_quant/
├── scanner/                 # 批量筛选模块
│   ├── __init__.py
│   ├── scanner.py           # 筛选引擎
│   └── filters.py           # 筛选条件定义
├── visualizer/              # K线图生成模块
│   ├── __init__.py
│   ├── chart_generator.py   # 图表生成器（可扩展副图）
│   └── panels.py            # 副图渲染器（PanelRenderer 基类 + 实现）
├── llm_scorer/              # LLM打分模块
│   ├── __init__.py
│   ├── scorer.py            # 两阶段打分引擎（TwoStageScorer）
│   ├── prompts.py           # Prompt 模板
│   └── clients/             # LLM 客户端
│       ├── __init__.py
│       ├── base.py          # LLMClient 基类
│       └── claude_client.py # Claude Opus 4.7 实现
├── portfolio/               # 组合回测模块
│   ├── __init__.py
│   ├── portfolio_engine.py  # 组合回测引擎
│   └── reporter.py          # 组合报告生成
├── scheduler/               # 定时任务模块
│   ├── __init__.py
│   ├── scheduler.py         # 任务调度器（APScheduler）
│   └── jobs.py              # 任务定义
├── output/                  # 输出目录
│   ├── candidates/          # 候选股票池 JSON
│   ├── charts/              # K线图 PNG
│   ├── scores/              # LLM 打分结果 JSON
│   ├── signals/             # 交易信号 JSON
│   └── portfolio/           # 组合回测报告
├── logs/                    # 日志目录
└── main.py                  # 新增子命令：scan, score, signal, portfolio, scheduler
```

## 7. 新增依赖

```
mplfinance>=0.12.0           # K线图绘制
anthropic>=0.40.0            # Claude API
apscheduler>=3.10.0          # 定时任务调度
chinese-calendar>=1.9.0      # 中国节假日判断
Pillow>=10.0.0               # 图片拼接
pyyaml>=6.0                  # 配置文件解析
```

## 8. 成本估算

| 项目 | 单次成本 | 每日成本 | 每月成本 |
|------|---------|---------|---------|
| 阶段 1 表格初筛 | $0.08 | $0.08 | $2.4 |
| 阶段 2 图形精筛（2 批） | $0.35 × 2 | $0.70 | $21.0 |
| **总计** | **$0.78** | **$0.78** | **$23.4** |

## 9. 性能估算

| 步骤 | 耗时 | 说明 |
|------|------|------|
| 数据拉取 | 5-10 分钟 | 增量更新，仅下载缺失数据 |
| 全市场扫描 | 15-20 分钟 | 单进程，可优化至 5-8 分钟 |
| K 线图生成 | 2-3 分钟 | 仅生成候选股票的图表 |
| LLM 打分 | 3-4 分钟 | 3 次 API 调用 |
| 信号生成 | < 1 分钟 | 纯计算 |
| **总计** | **25-38 分钟** | **收盘后 16:10 前完成** |

## 10. 配置文件

```yaml
# config.yaml
strategy: b1

llm:
  provider: claude
  api_key: ${CLAUDE_API_KEY}
  model: claude-opus-4-20250514
  timeout: 60
  max_retries: 2

scheduler:
  timezone: Asia/Shanghai
  cron: "30 15 * * 1-5"
  max_instances: 1

portfolio:
  initial_capital: 100000
  max_positions: 10
  slippage: 0.001
```

## 11. 环节详细设计索引

| 环节 | 文档 | 涉及模块 |
|------|------|---------|
| 1. 数据拉取 | [pipeline-01-data-fetch.md](pipeline/2026-04-29-pipeline-01-data-fetch.md) | fetcher/, adapter/ |
| 2. 筛选 + K线图 | [pipeline-02-scan-visualize.md](pipeline/2026-04-29-pipeline-02-scan-visualize.md) | scanner/, visualizer/ |
| 3. LLM 打分 | [pipeline-03-llm-scoring.md](pipeline/2026-04-29-pipeline-03-llm-scoring.md) | llm_scorer/ |
| 4. 回测 + 信号 | [pipeline-04-portfolio-signal.md](pipeline/2026-04-29-pipeline-04-portfolio-signal.md) | portfolio/, signal |
| 5. 定时调度 | [pipeline-05-scheduler.md](pipeline/2026-04-29-pipeline-05-scheduler.md) | scheduler/ |
