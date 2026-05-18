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
| 决策规则 | 复用 `tests/portfolio_b1_top2.py` 的 V2.1 规则全集（6 类卖出 + 槽位制 + 连续亏损冷却） | 已被回测验证（年化 62% / 回撤 -16%） |
| 评分来源 | **buy 候选用 V2 ML 评分**（`tests/scan_v2_style.check_one`），与回测一致；`output/scores/` 的 LLM 打分仅作 signal.json，不参与 advisor 决策 | 保证 advisor 行为与回测验证可对照；LLM 评分另列后续迭代 |
| 持仓来源 | `data/positions.json` 手动维护，仅填 4 字段 | 派生状态由 advisor 重放历史 bar 推导 |
| 已平仓记录 | `data/closed_trades.json`，advisor 输出 sell 动作时**不**写入；用户次日实盘成交后手动追加（含 `pnl_pct`） | advisor 不下单，无法确认成交；冷却状态依赖此文件 |
| 触发时间 | 工作日 16:00 | AkShare 日线 15:30~16:00 才稳定 |
| 邮件通道 | QQ SMTP `smtp.qq.com:465 SSL` + 授权码 | 零成本、无外部依赖 |
| 失败处理 | 每外部 IO 步骤重试 3 次×60s，全失败发错误邮件 | 避免错过信号 |
| 仓位制 | **槽位制**：强市 max_slots=2 单仓 50%；弱市 max_slots=1 单仓 40%；空槽即买，**不要求清零** | 与回测主循环 `portfolio_b1_top2.py:359-374` 一致 |
| 大盘判定 | 一律以 `idx_000001_SH`（上证）为准，不按板块映射 | 与回测主循环 308-309 行一致 |
| 买入价 | "明日开盘市价"；邮件估算价用今日收盘 ×1.001（仅提示） | 与回测一致；估算价标注"实际以开盘为准" |
| 邮件风格 | HTML 摘要 + 纯文本 fallback（`MIMEMultipart('alternative')`），全 inline style | QQ Mail / Outlook 兼容 |
| 总资金 | `positions.json.total_capital` 字段维护 | 与状态同处，避免环境变量分散 |

### 3.1 卖出规则全集（V2.1）

`api/portfolio/rules.py:calc_sell_signal` 必须实现全部 6 类，从 `tests/portfolio_b1_top2.py:205-265` 一对一搬运。

| # | 名称 | 触发条件 | 卖出比例 |
|---|---|---|---|
| 0 | 硬止损 | 弱市 `cur_profit ≤ -4%`；强市 `cur_profit ≤ -7%` | 1.0 |
| 1 | 跌破大哥黄 | `cur_close < cur_yellow` | 1.0 |
| 2 | 阴线放量 | `vol_r > 1.5 且 drop_pct > 5%`（drop_pct 按 open→close） | 1.0 |
| 3 | 破趋势白（曾上穿） | `above_white_once 且 cur_close < cur_white` | 1.0 |
| 4 | T+N 不涨即卖 | `hold_days ≥ 3 且 cur_profit < 2%` | 1.0 |
| 5 | 9 级分批止盈 | `cur_profit ≥ TP_LEVELS[next_lv-1]`（10/20/.../90%） | 1/3 |

判定顺序按 0 → 5；命中即返回，不继续判定。

### 3.2 槽位制 & 连续亏损冷却

| 字段 | 强市 (`market_is_strong=True`) | 弱市 |
|---|---|---|
| `max_slots` | 2 | 1 |
| `single_position_pct` | 0.50 | 0.40 |

冷却规则：advisor 启动时读取 `data/closed_trades.json`，按时间倒序统计**最近全清交易**：

- 连续 2 笔 `pnl_pct < 0` → 进入 10 个交易日冷却（`cooldown_until = today_index + 15`，与回测一致）
- 出现一笔 `pnl_pct ≥ 0` → 计数清零，冷却失效
- 冷却中 advisor 不输出 buy 动作，决策 JSON 的 `warnings` 写入"连续亏损冷却中，剩余 X 个交易日"

## 4. 模块划分

```
api/
├── advisor/                     ← 新增
│   ├── __init__.py
│   ├── decision_engine.py       决策核心
│   ├── position_state.py        派生状态重放
│   ├── cooldown.py              连续亏损冷却判定
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
- `buy_date`：实际成交日（T+1 早盘买入则填 T+1 日期）。
- `total_capital` 用于计算槽位金额；`cash` 缺省时由 `total_capital - sum(shares × cost_price)` 推算。
- 派生状态由 `replay_state` 推导，**不写回 `positions.json`**。
- `shares` 校验按板块：主板/创业板 100 整倍；科创板（68 开头）≥ 200 起，超出后允许 1 股递增；advisor 输出 sell 动作时按板块取整。

### 5.2 已平仓交易文件 `data/closed_trades.json`

advisor **只读不写**。用户在 advisor 提示卖出且第二日实盘成交后，手动追加一条记录：

```json
{
  "trades": [
    {
      "symbol": "600000",
      "buy_date": "2026-05-08",
      "sell_date": "2026-05-15",
      "buy_price": 12.35,
      "sell_price": 12.10,
      "shares": 1000,
      "ratio": 1.0,
      "pnl_pct": -2.02,
      "sell_reason": "跌破大哥黄"
    }
  ],
  "updated_at": "2026-05-15 21:00"
}
```

advisor 用 `pnl_pct` 与 `ratio` 判定连续亏损（仅 `ratio >= 1.0` 的全清记录计入连续计数）。文件不存在时视为无历史平仓，冷却不激活。

### 5.3 决策文件 `output/decisions/decision_YYYYMMDD.json`

```json
{
  "date": "2026-05-18",
  "next_trading_date": "2026-05-19",
  "market": {
    "index": "idx_000001_SH",
    "allow_buy": true,
    "is_strong": false,
    "max_slots": 1,
    "single_position_pct": 0.40
  },
  "cooldown": {
    "active": false,
    "remaining_days": 0
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
      "reason": "硬止损(-4%, 当前-4.32%)",
      "exec": "明日开盘市价"
    },
    {
      "kind": "buy",
      "symbol": "601318",
      "name": "中国平安",
      "amount": 40000,
      "estimated_price": 48.20,
      "estimated_shares": 800,
      "reason": "V2 ML 评分 Top1 + 大盘允许买入（弱市单仓 40%）",
      "exec": "明日开盘市价（估算价以今日收盘×1.001 计；实际以开盘为准）"
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

`kind ∈ {sell, buy, hold, wait}`；`tp_level_done` 表示**已完成的止盈档数**（0=未触发，2=已完成 +10% 与 +20% 两档，下一档为 +30%）。

### 5.4 邮件 HTML

布局自上而下：

1. 标题：`【量化日报】2026-05-18 · 大盘:允许买入/弱势`
2. 持仓概览表：代码 / 名称 / 持有天数 / 成本 / 现价 / 浮盈 / 当前止盈档（已完成档数）
3. 明日动作表：动作色块（卖=红 / 买=绿 / 观望/持有=灰）+ 执行价格说明 + 原因
4. 决策依据脚注：硬止损、跌破大哥黄、阴线放量、破趋势白、T+3、9 级止盈、槽位与冷却规则
5. 维护提示：本次卖出后请在 `data/closed_trades.json` 追加成交记录（`pnl_pct/ratio`），并更新 `positions.json` 的 `cash`
6. 失败邮件单独模板：失败步骤 + traceback 摘要

兼容性约束（HTML 必须满足）：

- 全部 inline style，禁用 `<style>` 块、`<link>`、`<script>`
- 用 `<table>` 布局，禁用 flex/grid/float
- 字号 ≥ 14px；动作色块用背景色（`background-color`）而非 `box-shadow`
- 同时构造纯文本 fallback：`MIMEMultipart('alternative')`，纯文本简单列出 holdings + actions

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
   │    ├─ 读 data/closed_trades.json → cooldown.compute_state(today_idx) → {active, until}
   │    ├─ 计算 market_strong / market_allow_buy（一律以 idx_000001_SH 为准）
   │    ├─ 派生 max_slots / single_position_pct（强 2/0.50 vs 弱 1/0.40）
   │    ├─ 对每只持仓：position_state.replay_state(pos, df_until_today)
   │    │     → calc_sell_signal(replayed_pos, df, today, market_strong)
   │    │     → 命中即输出 sell 动作；未命中输出 hold
   │    ├─ slots_left = max_slots - len(holdings)
   │    ├─ 若 slots_left > 0 且 market_allow_buy 且 not cooldown.active：
   │    │     调 scan_v2_style.check_one(symbol, today) 并发扫描全市场
   │    │     按 score 倒序取前 slots_left 只
   │    │     amount = total_capital × single_position_pct
   │    │     estimated_shares = floor(amount / (today_close × 1.001) / 100) × 100
   │    │     输出 buy 动作
   │    ├─ 若 slots_left > 0 且 (大盘不允许 或 冷却中)：输出 wait 动作（含原因）
   │    └─ 原子写 output/decisions/decision_YYYYMMDD.json（tmp + os.replace）
   └─ Step 7  notify            ★新增
        ├─ render_html(decision_json) + render_plain_text(decision_json)
        └─ email_sender.send(MIMEMultipart('alternative'))  ←─ 重试 3×60s
任一 Step 1/2/4/6 最终失败 → send_error_mail(step, traceback)
Step 7 自身最终失败 → 仅 logger.error，不再嵌套发邮件
```

### 6.1 关键约束

- **派生状态重放**：`replay_state(pos, df_until_today)` 从 `buy_date` **之后第一个交易日**开始遍历到今日（含），逐 bar 调用 `calc_sell_signal` 累加 `hold_days/tp_level_done/above_white_once/max_profit_pct`，但**忽略中间返回的卖出信号**。`buy_date` 当天 `hold_days=0`，第二个交易日 `hold_days=1`——与回测主循环 `portfolio_b1_top2.py:305-403` 的"i+1 才进入下一次 sell 评估"语义对齐。
- **next_trading_date**：循环 `today + N 天` 直到 `chinese_calendar.is_workday=True`；不可用时退化为只跳过周末。
- **estimated_price**：今日收盘 ×(1+0.001) 滑点估算，**仅作邮件提示**，不影响决策。邮件文案标注"实际以明日开盘为准"。
- **大盘判定**：advisor 只用 `idx_000001_SH` 一刀切，与回测主循环 308-309 行一致；`api/portfolio/rules.py` 保留 `pick_index_for` 但 advisor 不调用（留给后续多板块版本）。
- **槽位制 vs "未清零不补仓"**：advisor 使用槽位制（`slots_left > 0` 即可买入），与回测一致；早期设计文档中"未清零不补仓"作废。
- **冷却状态来源**：advisor 启动时读 `closed_trades.json`，按时间排序取最近全清记录（`ratio >= 1.0`）。连续 2 笔 `pnl_pct < 0` → `cooldown_until = today_idx + 15`（即 10 个交易日，与回测一致）；遇到一笔 ≥ 0 即清零。`today_idx` 由 `idx_000001_SH.csv` 的交易日序列推算。

### 6.2 退化场景

| 场景 | 行为 |
|---|---|
| `positions.json` 不存在 | 视为空仓，仍可推荐买入 |
| `closed_trades.json` 不存在 | 视为无历史，冷却不激活 |
| `scores_*.json` 不存在 | advisor 不依赖此文件；buy 候选直接来自 `scan_v2_style.check_one` |
| 大盘 `allow_buy=false` | 空仓位输出 `wait`，已持仓正常判 sell |
| 冷却激活 | 空仓位输出 `wait`（reason="连续亏损冷却中，剩余 X 个交易日"） |
| `CLAUDE_API_KEY` 未设置 | step4 跳过，advisor 仍照常运行（不依赖 LLM） |
| `QQ_EMAIL_PASS` 未设置 | step7 直接失败，仅落日志，无邮件 |
| AkShare 数据是否前复权 | 默认前复权（与现有 fetcher 一致）。advisor 检测到当日 `close` 相对昨日跳变 > 5% 时输出 warning，提示用户检查除权除息后的 cost_price |

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
    "max_slots_strong":          2,
    "max_slots_weak":            1,
    "single_position_pct_strong": 0.50,
    "single_position_pct_weak":   0.40,
    "cooldown_loss_streak":       2,    # 连续亏损笔数阈值
    "cooldown_days":              10,   # 冷却交易日数
    "retry_times":                3,
    "retry_interval_sec":         60,
}
```

调度器：`api/scheduler/scheduler.py` 的 cron 改成 `mon-fri 16:00`，`misfire_grace_time=3600` 保持不变。

## 8. 错误处理

- `api/utils/retry.py` 提供 `_retry(fn, times=3, interval=60, on_retry=log)`。
- 每个外部 IO step 用 `_retry` 包装。
- `daily_job` 最外层 try/except 捕获并触发 `send_error_mail`。
- **step7 邮件失败不再嵌套发邮件**：重试 3 次仍失败只 `logger.error`，不递归调用 `send_error_mail`。
- 错误邮件标题：`【量化日报-异常】<step>`，正文含失败步骤、时间、traceback 末 50 行。
- decision JSON 写入采用 `tmp + os.replace` 原子化，避免半文件。

## 9. 测试

无 CI 框架，手工运行 `pytest`：

| 用例 | 文件 | 验证点 |
|---|---|---|
| 空仓 + V2 ML Top → buy 动作金额（强市 50% / 弱市 40%） | `tests/test_decision_engine.py` | `actions[0].kind=='buy'`，amount 与强弱市档位一致 |
| 持仓 buy_date=T-3 + 涨幅<2% → T+3 sell 动作 | 同上 | `reason` 含 "T+3" |
| 持仓 cur_profit=-5% 弱市 → 硬止损 sell 动作 | 同上 | `reason` 含 "硬止损(-4%" |
| 持仓 cur_profit=-8% 强市 → 硬止损 sell 动作 | 同上 | `reason` 含 "硬止损(-7%" |
| 大盘 mock `allow_buy=False` → wait 动作 | 同上 | `actions[].kind=='wait'` |
| 弱市 max_slots=1 + 已有 1 持仓 → 不输出 buy | 同上 | `actions` 中无 `kind=='buy'` |
| 强市 max_slots=2 + 已有 1 持仓 → 输出 1 个 buy | 同上 | `actions` 中恰好 1 个 buy |
| `closed_trades.json` 最近 2 笔全清亏损 → 冷却激活 | `tests/test_cooldown.py` | `cooldown.active==True` 且 wait 动作含"冷却中" |
| 冷却中遇到一笔盈利 → 计数清零 | 同上 | `cooldown.active==False` |
| `replay_state` 还原状态与回测一致 | `tests/test_position_state_replay.py` | 给定 buy_date + 后续 5 根 bar，`hold_days==5` 且 `tp_level_done` 与回测匹配 |
| `replay_state` buy_date 当天 hold_days=0 边界 | 同上 | 仅传入到 buy_date 当天的数据，replay 后 `hold_days==0` |
| `estimated_shares` 100 股向下取整 + 资金不足 | `tests/test_decision_engine.py` | 资金 < 100 股成本时不输出 buy |
| email_sender 重试 + HTML 内容 + 纯文本 fallback | `tests/test_email_sender.py` | mock `smtplib.SMTP_SSL`，验证调用次数、`MIMEMultipart('alternative')` 结构 |

运行：`python -m pytest tests/test_decision_engine.py tests/test_position_state_replay.py tests/test_cooldown.py tests/test_email_sender.py -v`

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
# 卖出成交后追加平仓记录（必须填 pnl_pct 和 ratio，advisor 用其判定冷却）
vim data/closed_trades.json

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
| 派生状态重放与真实持仓走势不符（除权除息） | 卖出信号误判 | AkShare 默认前复权，历史 close 已调整。advisor 检测到当日 close 跳变 > 5% 时输出 warning，提示手动核对 cost_price |
| 用户忘记追加 `closed_trades.json` | 冷却失效 | 邮件维护提示明确写"卖出成交后必须追加 ratio + pnl_pct"；advisor 检测到上次 sell 动作日期在 closed_trades 中无对应记录时输出 warning |
| 评分体系与回测不完全一致 | advisor 实盘行为偏离回测验证 | advisor 的 buy 候选用 V2 ML 评分（与回测同源）；LLM 评分仅作 signal.json 备份，不进入决策 |
| QQ SMTP 限流/被封 | 邮件发不出 | 重试 + 错误日志；后续可加 Sentry/钉钉作降级通道（不在本期范围） |
| `positions.json` 字段填错 | 卖出/买入动作错乱 | advisor 启动时校验：symbol 6 位数字、shares > 0 且按板块取整、buy_date 在交易日历内；校验失败抛出并发错误邮件 |

## 13. 待用户确认事项

无。所有关键决策已对齐，未决项留作后续迭代。
