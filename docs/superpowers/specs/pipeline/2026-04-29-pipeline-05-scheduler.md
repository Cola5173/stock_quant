# 环节 5：定时任务调度

> 上游依赖：环节 1-4（串联所有环节）
> 下游消费：无（流水线终点）
> 输入：无（自动触发）
> 输出：串联执行环节 1-4 的所有输出

## 1. 概述

管理定时任务，在每个交易日收盘后自动执行完整流程（数据拉取 → 筛选 → K线图 → LLM打分 → 信号生成）。

## 2. 技术选型

**APScheduler**（轻量级，无需 Redis）

选择理由：
- 支持 Cron 表达式
- 支持后台运行
- 无需额外依赖
- 适合单机部署

## 3. 核心类

```python
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

class TradingScheduler:
    """交易调度器"""

    def __init__(self):
        self.scheduler = BackgroundScheduler()

    def start(self):
        self.scheduler.add_job(
            self.daily_job,
            trigger=CronTrigger(
                day_of_week='mon-fri',
                hour=15,
                minute=30
            ),
            id='daily_scan',
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600
        )
        self.scheduler.start()

    def daily_job(self):
        today = datetime.now().strftime("%Y-%m-%d")

        if not is_trading_day(today):
            logger.info(f"非交易日，跳过: {today}")
            return

        try:
            logger.info(f"开始执行每日任务: {today}")

            # 1. 拉取数据
            self._fetch_data(today)

            # 2. 检查持仓，生成卖出信号
            self._generate_sell_signals(today)

            # 3. 全市场扫描筛选
            candidates = self._scan_market(today)

            # 4. 生成K线图
            self._generate_charts(candidates, today)

            # 5. LLM打分（两阶段）
            top10 = self._llm_score(candidates, today)

            # 6. 生成买入信号
            self._generate_buy_signals(top10, today)

            logger.info(f"每日任务完成: {today}")

        except Exception as e:
            logger.error(f"每日任务失败: {e}")
```

## 4. 节假日处理

```python
def is_trading_day(date: str) -> bool:
    import chinese_calendar as calendar
    date_obj = datetime.strptime(date, "%Y-%m-%d")
    return calendar.is_workday(date_obj)
```

## 5. 错误处理

**日志记录：**
- 所有异常写入 `logs/scheduler_error.log`
- 包含时间戳、错误类型、堆栈跟踪

**告警机制：**
- 发送邮件通知（可选）
- 写入告警文件 `logs/alerts.log`

**手动补救：**
- 提供手动执行命令补救失败的任务
- 例如：`python main.py scan --date 2026-04-29`

## 6. 日志目录结构

```
stock_quant/
├── logs/
│   ├── scheduler.log        # 定时任务日志
│   ├── scanner.log          # 扫描日志
│   ├── data_fetch_error.log # 数据拉取错误
│   ├── llm_error.log        # LLM 调用错误
│   └── alerts.log           # 告警日志
```

## 7. CLI 命令

```bash
# 启动调度器（后台运行）
python main.py scheduler start

# 停止调度器
python main.py scheduler stop

# 查看调度器状态
python main.py scheduler status
```

**生产环境启动：**

```bash
nohup python main.py scheduler start > scheduler.log 2>&1 &
tail -f scheduler.log
```

## 8. 测试建议

**单元测试：**
- Scanner：使用历史数据验证筛选逻辑
- Visualizer：生成测试图片并人工检查
- Portfolio：对比手工计算结果

**集成测试：**
- 使用 2026-01-01 ~ 2026-01-31 数据运行完整流程
- 验证输出文件格式和内容

**LLM Prompt 测试：**
- 准备 10 只已知好坏的股票
- 人工评分 vs LLM 评分对比
- 迭代优化 Prompt
