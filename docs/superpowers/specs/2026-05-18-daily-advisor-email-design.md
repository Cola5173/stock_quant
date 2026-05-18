# 每日收盘后自动决策与邮件推送 · 设计文档

- **日期**：2026-05-18
- **分支**：feature/v1.0.0
- **目标**：每个交易日 16:00 自动拉取最新数据 → 基于 V2.1 卖出规则 + LLM Top 推荐生成"明日动作单" → QQ 邮箱推送 HTML 摘要

---

## 1. 背景

现有 `api/scheduler/jobs.py:daily_job` 已串好"数据→Scanner→K线图→LLM 打分→signal" 五步流水线，但只产出"明天可买清单"，缺少：

- 真实持仓的卖出/止盈/止损建议
- 大盘强弱过滤导致的"今日观望"提示
- 任何外部通知（邮件/IM）

回测脚本 `tests/portfolio_b1_top2.py` 已经验证过一套完整 V2.1 规则（5 类卖出 + 大盘过滤 + 9 级分批止盈），但锁在 `tests/` 目录、未模块化，不能被实盘流水线复用。

## 2. 范围

**包含**

- 在 `daily_job` 之后追加 step6 决策、step7 通知。
- 抽离 V2.1 卖出规则到 `api/portfolio/rules.py`，回测 + 实盘共用。
- 新增 `api/advisor/` 决策引擎模块。
- 新增 `api/notifier/` 邮件模块（QQ SMTP）。
- 调度时间从 15:30 调整为 16:00。
- `main.py` 新增 `advisor` 命令便于手动调试。

**不包含**

- 自动下单 / 券商 API 接入。
- 真实账户对账。
- 多用户、多收件人路由。
- IM（Slack/钉钉/微信）通知。

## 3. 关键决策

| 议题 | 决策 | 理由 |
|---|---|---|
| 决策规则 | 复用 `tests/portfolio_b1_top2.py` 的 V2.1 规则 | 已被回测验证（年化 62% / 回撤 -16%） |
| 持仓来源 | `data/positions.json` 手动维护，仅填 4 字段 | 派生状态由 advisor 重放历史 bar 推导，避免手维护出错 |
| 触发时间 | 工作日 16:00 | AkShare 日线 15:30~16:00 才稳定 |
| 邮件通道 | QQ SMTP `smtp.qq.com:465 SSL` + 授权码 | 零成本、无外部依赖 |
| 失败处理 | 每外部 IO 步骤重试 3 次×60s，全失败发错误邮件 | 避免错过信号 |
| 仓位制 | Top-2 等额 50%/50%，未清零不补仓 | 与 V2.1 回测一致 |
| 买入价 | "明日开盘市价" | 与回测一致 |
| 邮件风格 | HTML 摘要：持仓表 + 明日动作表 | 手机查看友好 |
| 总资金 | `positions.json.total_capital` 字段维护 | 与状态同处，避免环境变量分散 |

## 4. 模块划分

```
api/
├── advisor/                     ← 新增
│   ├── __init__.py
│   ├── decision_engine.py       决策核心
│   ├── position_state.py        派生状态重放
│   └── decision_schema.py       Decision/ActionItem dataclass
├── portfolio/
│   ├── rules.py                 ← 新增（从 tests 抽出）
│   ├── portfolio_engine.py      （保持原位）
│   └── reporter.py
├── notifier/                    ← 新增
│   ├── __init__.py
│   ├── email_sender.py          QQ SMTP 发送
│   └── templates.py             HTML 模板
├── utils/
│   └── retry.py                 ← 新增 _retry()
└── scheduler/jobs.py            追加 step6/step7

main.py                          ← 追加 advisor 子命令
api/config/settings.py           ← 追加 POSITIONS_FILE / DECISIONS_DIR / EMAIL_CONFIG / ADVISOR_CONFIG
docs/superpowers/specs/          ← 本文件
```

`tests/portfolio_b1_top2.py` 内部改成 `from api.portfolio.rules import ...`，行为不变。

## 5. 数据模型

### 5.1 持仓文件 `data/positions.json`

```json
{
  "total_capital": 100000,
  "cash": 0,
  "positions": [
    {
      "symbol": "600000",
      "shares": 1000,
      "cost_price": 12.35,
      "buy_date": "2026-05-12"
    }
  ],
  "updated_at": "2026-05-18 16:00"
}
```

约定：

- 用户只填 `symbol / shares / cost_price / buy_date`。
- `total_capital` 用于计算 50% 仓位金额；`cash` 缺省时由 `total_capital - sum(shares × cost_price)` 推算。
- 派生状态（`hold_days / max_profit_pct / above_white_once / tp_level_done`）由 `replay_state` 从 `buy_date` 起遍历历史 bar 重放。

### 5.2 决策文件 `output/decisions/decision_YYYYMMDD.json`

```json
{
  "date": "2026-05-18",
  "next_trading_date": "2026-05-19",
  "market": {
    "index": "idx_000001_SH",
    "allow_buy": true,
    "is_strong": false
  },
  "holdings": [
    {
      "symbol": "600000",
      "name": "浦发银行",
      "shares": 1000,
      "cost_price": 12.35,
      "current_close": 13.10,
      "profit_pct": 6.07,
      "hold_days": 4,
      "tp_level_done": 0,
      "above_white_once": true
    }
  ],
  "actions": [
    {
      "kind": "sell",
      "symbol": "600000",
      "name": "浦发银行",
      "shares": 1000,
      "ratio": 1.0,
      "reason": "T+3 涨幅<2%(当前+1.20%)",
      "exec": "明日开盘市价"
    },
    {
      "kind": "buy",
      "symbol": "601318",
      "name": "中国平安",
      "amount": 50000,
      "estimated_price": 48.20,
      "estimated_shares": 1000,
      "reason": "LLM Top1 + 大盘允许买入",
      "exec": "明日开盘市价"
    },
    {
      "kind": "hold",
      "symbol": "000001",
      "name": "平安银行",
      "reason": "持仓中且无卖出信号"
    },
    {
      "kind": "wait",
      "reason": "大盘弱：上证收盘 < 大哥黄"
    }
  ],
  "warnings": []
}
```

`kind ∈ {sell, buy, hold, wait}`。

### 5.3 邮件 HTML

布局自上而下：

1. 标题：`【量化日报】2026-05-18 · 大盘:允许买入/弱势`
2. 持仓概览表：代码 / 名称 / 持有天数 / 成本 / 现价 / 浮盈 / 当前止盈档
3. 明日动作表：动作色块（卖=红 / 买=绿 / 观望/持有=灰）+ 执行价格说明 + 原因
4. 决策依据脚注：T+3、跌破大哥黄、阴线放量、分批止盈等规则简要列示
5. 失败邮件单独模板：失败步骤 + traceback 摘要

## 6. 数据流

```
16:00 cron 触发
   │
   ▼
daily_job(strategy='b1', source='akshare')
   ├─ Step 1  fetch_data        ←─ 重试 3×60s
   ├─ Step 2  scan              ←─ 重试 3×60s
   ├─ Step 3  generate_charts
   ├─ Step 4  llm_score         ←─ 重试 3×60s（无 KEY 跳过，不算失败）
   ├─ Step 5  generate_signals
   ├─ Step 6  decide            ★新增
   │    ├─ 读 data/positions.json
   │    ├─ position_state.replay_state(pos, 历史 bar)
   │    ├─ 每只持仓 calc_sell_signal → sell 动作
   │    ├─ market_allow_buy(today)
   │    ├─ 若 大盘允许 + 持仓全清 → LLM TopN 前 (2-持仓数) 只 → buy 动作
   │    │     amount = total_capital × 0.5
   │    │     estimated_shares = floor(amount / open_est / 100) * 100
   │    ├─ 持仓中无卖出信号 → hold 动作
   │    ├─ 大盘弱 + 空仓位 → wait 动作
   │    └─ 写 output/decisions/decision_YYYYMMDD.json
   └─ Step 7  notify            ★新增
        ├─ render_html(decision_json)
        └─ email_sender.send()  ←─ 重试 3×60s
任一 Step 1/2/4/6/7 最终失败 → send_error_mail(step, traceback)
```

### 6.1 关键约束

- **派生状态重放**：`replay_state(pos, df_until_today)` 从 `buy_date` 当日起按交易日逐 bar 调用 `calc_sell_signal` 累加 `hold_days/tp_level_done/above_white_once/max_profit_pct`，但**忽略中间返回的卖出信号**——卖出判断只在最新一根 bar 上采纳。这样保证 advisor 推导的状态与回测一致。
- **next_trading_date**：`chinese_calendar.is_workday` 找下一个工作日；不可用时 `today + 1 day` 兜底。
- **estimated_price**：今日收盘 ×(1+0.001) 滑点估算，仅作邮件提示不影响决策。
- **未清零不补仓**：只要还有未平的旧持仓，本日不输出 buy 动作（与回测一致）。

### 6.2 退化场景

| 场景 | 行为 |
|---|---|
| `positions.json` 不存在 | 视为空仓，仍可推荐买入 |
| `scores_*.json` 不存在但 `candidates_*.json` 存在 | 用 candidates 前 N |
| 大盘 `allow_buy=false` | 空仓位输出 `wait`，已持仓正常判 sell |
| `CLAUDE_API_KEY` 未设置 | 跳过 step4，candidates 兜底 |
| `QQ_EMAIL_PASS` 未设置 | step7 直接失败，错误日志，无邮件 |

## 7. 配置

```python
# api/config/settings.py
POSITIONS_FILE = _abs("data/positions.json")
DECISIONS_DIR  = _abs("output/decisions")

EMAIL_CONFIG = {
    "host":        "smtp.qq.com",
    "port":        465,
    "use_ssl":     True,
    "user":        _os.getenv("QQ_EMAIL_USER", ""),
    "password":    _os.getenv("QQ_EMAIL_PASS", ""),  # 授权码，非登录密码
    "to":          _os.getenv("QQ_EMAIL_TO",   ""),
    "sender_name": "Stock Quant Daily",
}

ADVISOR_CONFIG = {
    "max_positions":       2,
    "single_position_pct": 0.5,
    "retry_times":         3,
    "retry_interval_sec":  60,
}
```

调度器：`api/scheduler/scheduler.py` 的 cron 改成 `mon-fri 16:00`，`misfire_grace_time=3600` 保持不变。

## 8. 错误处理

- `api/utils/retry.py` 提供 `_retry(fn, times=3, interval=60, on_retry=log)`。
- 每个外部 IO step 用 `_retry` 包装。
- `daily_job` 最外层 try/except 捕获并触发 `send_error_mail`。
- `send_error_mail` 自身失败只 log，不再嵌套。
- 错误邮件标题：`【量化日报-异常】<step>`，正文含失败步骤、时间、traceback 末 50 行。

## 9. 测试

无 CI 框架，手工运行 `pytest`：

| 用例 | 文件 | 验证点 |
|---|---|---|
| 空仓 + LLM Top → buy 动作金额 | `tests/test_decision_engine.py` | `actions[0].kind=='buy'`，`amount==total_capital*0.5` |
| 持仓 buy_date=T-3 + 涨幅<2% → sell 动作 | 同上 | `actions[0].reason` 含 "T+3" |
| 大盘 mock `allow_buy=False` → wait 动作 | 同上 | `actions[].kind` 包含 "wait" |
| `replay_state` 还原状态与回测一致 | `tests/test_position_state_replay.py` | 给定固定 bar，对比 `tp_level_done / above_white_once` |
| email_sender 重试 + HTML 内容 | `tests/test_email_sender.py` | mock `smtplib.SMTP_SSL`，验证调用次数与正文 |

运行：`python -m pytest tests/test_decision_engine.py tests/test_position_state_replay.py tests/test_email_sender.py -v`

## 10. CLI

`main.py` 新增 `advisor` 子命令：

```bash
# 完整跑一次决策 + 邮件
python main.py advisor --date 2026-05-18

# 仅生成决策，不发邮件
python main.py advisor --date 2026-05-18 --no-email

# 用已有 decision 文件仅发邮件（调试模板）
python main.py advisor --date 2026-05-18 --email-only
```

`--date` 缺省取今日。调度器内部仍走 `daily_job`，advisor 命令是 step6+step7 的独立入口。

## 11. 部署 & 运行

```bash
# 1. 安装依赖（已存在的 chinese_calendar 必须）
pip install -r requirements.txt

# 2. 配置 QQ 邮箱（一次性）
# 登录 QQ 邮箱 → 设置 → 账户 → 开启 SMTP → 生成授权码
export QQ_EMAIL_USER="xxxx@qq.com"
export QQ_EMAIL_PASS="授权码"
export QQ_EMAIL_TO="xxxx@qq.com"

# 3. 维护持仓（每次实盘交易后手动更新）
vim data/positions.json

# 4. 启动调度器
python main.py scheduler start --strategy b1 --source akshare

# 调试
python main.py advisor --date 2026-05-18         # 完整跑一次
python main.py advisor --date 2026-05-18 --no-email
python main.py advisor --date 2026-05-18 --email-only
```

## 12. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| AkShare 16:00 仍未刷新 | 决策依据缺当日数据 | 重试 3×60s；若仍失败发错误邮件，由用户判断是否手动重跑 |
| 派生状态重放与真实持仓走势不符（如除权除息） | 卖出信号误判 | 状态字段全部基于价格序列与 cost_price，不涉及现金流；除权日需用户手动调整 cost_price |
| QQ SMTP 限流/被封 | 邮件发不出 | 重试 + 错误日志；后续可加 Sentry/钉钉作降级通道（不在本期范围） |
| `positions.json` 字段填错 | 卖出/买入动作错乱 | advisor 启动时做基本校验：symbol 6 位数字、shares > 0 且 100 整数倍、buy_date 在交易日历内 |

## 13. 待用户确认事项

无。所有关键决策已对齐，未决项留作后续迭代。
